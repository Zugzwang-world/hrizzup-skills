# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Check that the links behind a post open, and say what is at the end of each one.

Give it links on the command line, or `--file` (any text: a brief, a post, a list), from which it
takes every web address. For each link it reports: url, finalUrl, status, ok, redirects, contentType,
title, lastModified, checkedAt and problem. A dead link is a finding, not a failure: it still exits 0.

It is careful with other people's sites and with your machine:
- Only `https://` links are checked; `http://` is refused, and so is any link whose host has an
  address that isn't on the public internet (your own machine, your network, a cloud's metadata
  address), whether the link says so or a redirect does. It connects to the address it checked,
  with TLS for the host's name. Redirects are followed by hand, each checked again, at most 5.
- `HEAD` first, then `GET` if the site refuses it; at most 64 KiB of a page is read (for its title);
  no cookies; one request to a host every `--delay` seconds; a Retry-After of up to 30 seconds is
  waited for once. It names itself in its user agent.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 it ran
(whatever the links said); 2 bad input; 3 this Python is too old (3.10 or newer is needed).
"""

from __future__ import annotations

import argparse
import html
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import unicodedata
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin, urlsplit

USER_AGENT = "hrizzup-skills-link-check/1.0 (+https://github.com/Zugzwang-world/hrizzup-skills)"
MAX_REDIRECTS = 5
MAX_READ = 64 * 1024
MAX_LINKS = 50
RETRY_AFTER_LIMIT = 30
TITLE_MAX = 200
HTML_TYPES = ("text/html", "application/xhtml+xml")
LINK_IN_TEXT = re.compile(r"https?://[^\s<>\"'`\]\[]+", re.I)
TITLE_TAG_ENDS = b">\t\n\r /"  # what may follow "<title" for it to be the tag
CHARSET = re.compile(r"charset=([A-Za-z0-9._-]+)", re.I)
HOST_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.?$")
PATH_SAFE = "/%:@!$&'()*+,;=-._~"  # kept as they are: the characters a path may hold, and existing %-escapes
QUERY_SAFE = "/?%:@!$&'()*+,;=-._~"


class Refused(Exception):
    """A link this tool won't visit, and why."""


class NetworkProblem(Exception):
    """The request didn't get an answer. `kind` is connect, tls, timeout, reset or other."""

    def __init__(self, message, kind):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------------------------
# Which addresses are fine to visit
# ---------------------------------------------------------------------------------------------

NAT64 = ipaddress.ip_network("64:ff9b::/96")  # carries an IPv4 address in its last 32 bits
NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")  # for use inside one network
SIX_TO_FOUR = ipaddress.ip_network("2002::/16")  # a tunnel: the IPv4 address inside isn't the host that answers
TEREDO = ipaddress.ip_network("2001::/32")  # a tunnel, likewise
SIX_TO_FOUR_RELAY = ipaddress.ip_network("192.88.99.0/24")


def unsafe_reason(address):
    """Why an IP address (as text) must not be visited; None when it is on the public internet. It fails
    closed. 6to4 and Teredo addresses are refused outright (the IPv4 address in one doesn't say which host
    answers). An IPv4-mapped (::ffff:a.b.c.d) or NAT64 (64:ff9b::/96) address must also carry a public IPv4
    address. Every address then has its own checks applied."""
    try:
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return "isn't an address"
    nat64 = False
    if ip.version == 6:
        if ip in SIX_TO_FOUR or ip in TEREDO:
            return "is a tunnel address (6to4 or Teredo), which doesn't say which host answers"
        if ip.ipv4_mapped is not None:
            reason = unsafe_reason(str(ip.ipv4_mapped))
            if reason:
                return reason
        if ip in NAT64:
            nat64 = True
            inner = ipaddress.IPv4Address(ip.packed[-4:])
            reason = unsafe_reason(str(inner))
            if reason:
                return "carries %s, which %s" % (inner, reason)
        if ip in NAT64_LOCAL:
            return "is a NAT64 address for use inside one network"
        if ip.is_site_local:
            return "is a site-local address (a private network's)"
    elif ip in SIX_TO_FOUR_RELAY:
        return "is a 6to4 relay address, which isn't a site"
    checks = (
        ("is_unspecified", "is an unspecified address"),
        ("is_loopback", "is this machine's own address"),
        ("is_link_local", "is a link-local address (such as a cloud's metadata service)"),
        ("is_private", "is on a private network"),
        ("is_multicast", "is a multicast address"),
        ("is_reserved", "is a reserved address"),
    )
    for attribute, reason in checks:
        if nat64 and attribute == "is_reserved":
            continue  # 64:ff9b::/96 sits inside ::/8, which Python calls reserved; its IPv4 address was judged above
        if getattr(ip, attribute):
            return reason
    if not ip.is_global:
        return "isn't on the public internet"
    return None


def is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def resolve(host, port):
    """The addresses a host name resolves to (a function of its own, so tests can replace it)."""
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise NetworkProblem("the address doesn't resolve (no such host)", "connect")
    except UnicodeError:
        raise NetworkProblem("the host name isn't one a browser could open", "connect")
    addresses = []
    for entry in found:
        if entry[4][0] not in addresses:
            addresses.append(entry[4][0])
    return addresses


def vet(url):
    """(host, port, path with query) of a link, as it will be requested, or Refused. Doesn't touch the
    network. The host is in its ASCII form and the path and query are percent-encoded, so no space, control
    character or non-ASCII letter ever reaches a request line."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise Refused("isn't a web address")
    if parts.scheme.lower() != "https":
        raise Refused("only https:// links are checked (this one is %s)" % (
            (parts.scheme + "://") if parts.scheme else "not a web address"))
    host = parts.hostname
    if not host:
        raise Refused("has no host name")
    if parts.username or parts.password:
        raise Refused("has a user name or password in it, which this tool never sends")
    if port not in (None, 443):
        raise Refused("uses port %d; only the standard port is checked" % port)
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise Refused("has a host name that can't be opened")
    if not HOST_NAME.match(host) and not is_ip(host):
        raise Refused("has a host name that can't be opened")
    path = quote(parts.path or "/", safe=PATH_SAFE)
    if parts.query:
        path += "?" + quote(parts.query, safe=QUERY_SAFE)
    return host, 443, path


def public_addresses(host, port):
    """The host's addresses, every one of them public, or Refused."""
    addresses = [host] if is_ip(host) else resolve(host, port)
    for address in addresses:
        reason = unsafe_reason(address)
        if reason:
            raise Refused("is refused: %s's address %s %s" % (host, address, reason))
    return addresses


# ---------------------------------------------------------------------------------------------
# One request, and the manners around it
# ---------------------------------------------------------------------------------------------

class PinnedConnection(http.client.HTTPSConnection):
    """HTTPS to an address already checked, with TLS for the host's name."""

    def __init__(self, host, address, port, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self.pinned_address = address
        self.tls_context = context
        self.raw = None  # the plain socket, kept so the deadline can cut it
        self.aborted = False

    def connect(self):
        raw = socket.create_connection((self.pinned_address, self.port), timeout=self.timeout)
        self.raw = raw
        try:
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise

    def abort(self):
        """Cut the connection from another thread (the deadline's): a read that is waiting ends at once."""
        self.aborted = True
        for sock in (self.sock, self.raw):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


def problem_from(error, timeout):
    """The NetworkProblem a socket, TLS or HTTP error stands for."""
    if isinstance(error, ssl.SSLCertVerificationError):
        return NetworkProblem("its certificate isn't trusted (%s)" % (
            clean(str(getattr(error, "verify_message", "") or ""), 100) or "verification failed"), "tls")
    if isinstance(error, ssl.SSLError):
        return NetworkProblem("the secure connection failed (%s)" % (
            clean(str(getattr(error, "reason", "") or ""), 100) or "TLS error"), "tls")
    if isinstance(error, socket.timeout):
        return NetworkProblem("no answer in %s seconds" % timeout, "timeout")
    if isinstance(error, (http.client.RemoteDisconnected, ConnectionResetError, http.client.BadStatusLine)):
        return NetworkProblem("the site closed the connection without answering", "reset")
    if isinstance(error, http.client.HTTPException):
        return NetworkProblem("the site's answer wasn't valid HTTP (%s)" % type(error).__name__, "other")
    if isinstance(error, (UnicodeError, ValueError)):
        return NetworkProblem("the link can't be sent as a request (%s)" % type(error).__name__, "other")
    return NetworkProblem("couldn't connect (%s)" % (getattr(error, "strerror", None) or type(error).__name__), "connect")


def fetch(host, address, port, method, path, timeout):
    """One request to a checked address: (status, headers with lower-case names, up to 64 KiB of body).
    The whole request, connecting and reading, gets `timeout` seconds in all: a site that answers a byte at
    a time is cut off at the deadline, not waited for. A function of its own, so tests can replace it."""
    context = ssl.create_default_context()
    connection = PinnedConnection(host, address, port, timeout, context)
    watchdog = threading.Timer(timeout, connection.abort)
    watchdog.daemon = True
    watchdog.start()
    late = NetworkProblem("no complete answer in %s seconds" % timeout, "timeout")
    try:
        connection.request(method, path, headers={
            "User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8", "Accept-Encoding": "gzip, identity",
            "Connection": "close",
        })
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        body = response.read(MAX_READ) if method == "GET" else b""
        if connection.aborted:
            raise late  # the deadline cut the reading short
        return response.status, headers, body
    except (OSError, http.client.HTTPException, ValueError) as error:
        if connection.aborted:
            raise late
        raise problem_from(error, timeout)
    finally:
        watchdog.cancel()
        connection.close()


class Visitor:
    """Visits links one at a time, one request to a host per `delay` seconds."""

    def __init__(self, delay=1.0, timeout=15.0, sleep=time.sleep, clock=time.monotonic):
        self.delay, self.timeout, self.sleep, self.clock = delay, timeout, sleep, clock
        self.last = {}
        self.waited = False  # whether this link has already had its one Retry-After wait

    def begin_link(self):
        self.waited = False

    def throttle(self, host):
        if host in self.last:
            wait = self.last[host] + self.delay - self.clock()
            if wait > 0:
                self.sleep(wait)
        self.last[host] = self.clock()

    def request(self, host, port, addresses, method, path):
        """One request, to the first address that answers. A link waits once, in all, for a short Retry-After."""
        while True:
            self.throttle(host)
            failure = None
            for address in addresses:
                try:
                    status, headers, body = fetch(host, address, port, method, path, self.timeout)
                    break
                except NetworkProblem as error:
                    failure = error
                    if error.kind != "connect":
                        raise
            else:
                raise failure or NetworkProblem("no address to connect to", "connect")
            if status in (429, 503) and "retry-after" in headers and not self.waited:
                seconds = retry_after_seconds(headers["retry-after"])
                if seconds is not None and seconds <= RETRY_AFTER_LIMIT:
                    self.waited = True
                    self.sleep(seconds)
                    continue
            return status, headers, body

    def page(self, host, port, addresses, path):
        """(status, headers, body) of a page: HEAD first, then GET when HEAD is refused, or when the page is
        HTML and its title is wanted."""
        try:
            status, headers, body = self.request(host, port, addresses, "HEAD", path)
        except NetworkProblem as error:
            if error.kind != "reset":
                raise
            return self.request(host, port, addresses, "GET", path)
        if status >= 400:
            return self.request(host, port, addresses, "GET", path)
        if 200 <= status < 300 and media_type(headers) in HTML_TYPES:
            try:
                return self.request(host, port, addresses, "GET", path)
            except NetworkProblem:
                return status, headers, b""
        return status, headers, body


def retry_after_seconds(value):
    value = value.strip()
    if value.isascii() and value.isdigit():  # not "2" with a superscript or an Arabic-Indic digit
        return int(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, int((moment - datetime.now(timezone.utc)).total_seconds()))


def media_type(headers):
    return headers.get("content-type", "").split(";")[0].strip().lower()


def clean(text, limit):
    """Text from a site, made safe for a report: no control, format or invisible characters, one space
    between words."""
    kept = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    return " ".join(kept.split())[:limit]


def find_title(body):
    """The bytes between the first `<title ...>` and `</title` of a page, or None, in one pass: every search
    moves forward, so even a page that is nothing but `<title>` takes no longer than its length. (The page is
    lower-cased as bytes, which changes only ASCII letters, so positions in it are positions in the page.)"""
    lowered = body.lower()
    start = lowered.find(b"<title")
    while start != -1:
        follower = lowered[start + 6:start + 7]
        if follower and follower in TITLE_TAG_ENDS:
            opened = lowered.find(b">", start)
            if opened == -1:
                return None
            closed = lowered.find(b"</title", opened)
            return None if closed == -1 else body[opened + 1:closed]
        start = lowered.find(b"<title", start + 6)
    return None


def page_title(headers, body):
    if not body or media_type(headers) not in HTML_TYPES:
        return None
    encoding = headers.get("content-encoding", "identity").strip().lower()
    if encoding in ("gzip", "x-gzip"):
        try:
            # only the first 64 KiB of what it unpacks to: a small file can unpack to gigabytes
            body = zlib.decompressobj(31).decompress(body, MAX_READ)
        except zlib.error:
            return None
    elif encoding != "identity":
        return None
    found = find_title(body[:MAX_READ])
    if found is None:
        return None
    charset = CHARSET.search(headers.get("content-type", ""))
    try:
        text = found.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        text = found.decode("utf-8", errors="replace")
    return clean(html.unescape(text), TITLE_MAX) or None


def explain(status):
    if status == 404 or status == 410:
        return "not found (%d): the page is gone or the address is wrong" % status
    if status in (401, 403):
        return "refused the request (%d): it may need a login, or only a person's browser" % status
    if status == 429:
        return "asked to slow down (429) and gave no short wait"
    if status >= 500:
        return "the site had an error (%d)" % status
    if status >= 400:
        return "the site answered %d" % status
    return None


# ---------------------------------------------------------------------------------------------
# Checking a link
# ---------------------------------------------------------------------------------------------

def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_link(url, visitor):
    """The report for one link (every field, see the top of this file). Never raises: one odd link
    must not stop the run."""
    report = {"url": url, "finalUrl": None, "status": None, "ok": False, "redirects": 0, "contentType": None,
              "title": None, "lastModified": None, "checkedAt": now_text(), "problem": None}
    visitor.begin_link()
    try:
        follow(url, visitor, report)
    except Exception as error:  # a last resort, for a case nobody thought of
        report["ok"] = False
        report["problem"] = "this tool hit an error it didn't expect (%s), so the link was not checked" % type(error).__name__
    return report


def follow(url, visitor, report):
    """Visit a link and what it redirects to, filling in its report."""
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        try:
            host, port, path = vet(current)
            addresses = public_addresses(host, port)
        except Refused as error:
            report["problem"] = str(error) if hop == 0 else "redirects to %s, not followed: %s" % (clean(current, 300), error)
            return
        except NetworkProblem as error:
            report["problem"] = str(error)
            return
        report["redirects"] = hop  # a redirect counts once its target is accepted
        try:
            status, headers, body = visitor.page(host, port, addresses, path)
        except NetworkProblem as error:
            report["problem"] = str(error)
            return
        report["finalUrl"], report["status"] = "https://" + host + path, status
        report["contentType"] = clean(media_type(headers), 100) or None
        report["lastModified"] = clean(headers.get("last-modified", ""), 60) or None
        if 300 <= status < 400 and headers.get("location"):
            if hop == MAX_REDIRECTS:
                report["problem"] = "more than %d redirects" % MAX_REDIRECTS
                return
            try:
                current = urljoin(current, headers["location"].strip())
            except ValueError:
                report["problem"] = "redirects to an address that isn't a web address"
                return
            continue
        if 300 <= status < 400:
            report["problem"] = "redirects (%d) but doesn't say where" % status
            return
        report["ok"] = 200 <= status < 300
        report["problem"] = None if report["ok"] else explain(status)
        report["title"] = page_title(headers, body)
        return


def links_in(text):
    """Every web address in a text, once each, in order, without the punctuation around it."""
    found = []
    for match in LINK_IN_TEXT.findall(text):
        link = match
        while link and (link[-1] in ".,;:!?*_" or (link[-1] == ")" and link.count(")") > link.count("("))):
            link = link[:-1]
        if link and link not in found:
            found.append(link)
    return found


def markdown_table(reports):
    def cell(value):
        return clean(str(value), 400).replace("|", "\\|") if value not in (None, "") else "-"
    rows = ["| Link | Status | Opens | Redirects | Title | Problem |", "|---|---|---|---|---|---|"]
    for r in reports:
        rows.append("| %s | %s | %s | %s | %s | %s |" % (
            cell(r["url"]), cell(r["status"]), "yes" if r["ok"] else "no", r["redirects"], cell(r["title"]), cell(r["problem"])))
    return "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------------------------

def make_parser():
    parser = argparse.ArgumentParser(
        prog="check_links.py",
        description="Check that the links behind a post open, and say what is at the end of each one.",
        epilog="Example: uv run scripts/check_links.py https://example.com/a --json links.json",
    )
    parser.add_argument("urls", nargs="*", help="the links to check (https:// only)")
    parser.add_argument("--file", help="a text file to take every web address from (a brief, a post, a list)")
    parser.add_argument("--section", help="with --file, take the addresses only from the markdown section with this heading, "
                                          "such as Sources (a brief's other sections quote other agents' posts)")
    parser.add_argument("--json", dest="json_out", help="write the reports as JSON to this file")
    parser.add_argument("--markdown", dest="markdown_out", help="write the reports as a Markdown table to this file")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between two requests to one host (default 1.0)")
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="seconds each request may take in all, however slowly the site answers (default 15)")
    return parser


def finish(ok, outputs, checks, problem, code):
    print(json.dumps({"ok": ok, "outputs": outputs, "checks": checks, "problem": problem}, ensure_ascii=False))
    return code


def write_report(path, text):
    data = text.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return {"path": path, "bytes": len(data), "width": None, "height": None, "seconds": None}


def section_of(text, name):
    """The lines of the markdown section whose `## ` heading is `name`, up to the next `## ` heading; or None."""
    found, inside = [], False
    for line in text.split("\n"):
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip() == name.strip()
            continue
        if inside:
            found.append(line)
    return "\n".join(found) if inside else None


def output_problem(paths):
    """Why an output file can't be written (its folder is missing or locked), or None."""
    for path in paths:
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
            return "the folder for %s doesn't exist or can't be written to" % path
    return None


def main(argv=None, visitor=None):
    if sys.version_info < (3, 10):
        print("check_links.py needs Python 3.10 or newer", file=sys.stderr)
        return finish(False, [], [], "needs Python 3.10 or newer", 3)
    args = make_parser().parse_args(argv)
    urls = [u.strip() for u in args.urls if u.strip()]
    targets = [os.path.abspath(p) for p in (args.json_out, args.markdown_out) if p]
    clash = None
    if len(set(targets)) != len(targets):
        clash = "--json and --markdown name the same file"
    elif args.file and os.path.abspath(args.file) in targets:
        clash = "an output would overwrite --file, an input"
    elif args.section and not args.file:
        clash = "--section needs --file"
    else:
        clash = output_problem([p for p in (args.json_out, args.markdown_out) if p])  # before any request is made
    if clash:
        print("check_links.py: " + clash, file=sys.stderr)
        return finish(False, [], [], clash, 2)
    try:
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                text = f.read()
            if args.section:
                text = section_of(text, args.section)
                if text is None:
                    message = "%s has no `## %s` section" % (args.file, args.section)
                    print("check_links.py: " + message, file=sys.stderr)
                    return finish(False, [], [], message, 2)
            for link in links_in(text):
                if link not in urls:
                    urls.append(link)
    except (OSError, UnicodeDecodeError) as error:
        message = "can't read %s: %s" % (args.file, error)
        print("check_links.py: " + message, file=sys.stderr)
        return finish(False, [], [], message, 2)
    problem = None
    if not urls:
        problem = "no links: give some on the command line, or --file with a text that holds them"
    elif len(urls) > MAX_LINKS:
        problem = "%d links; at most %d a run (be kind to the sites)" % (len(urls), MAX_LINKS)
    elif args.delay < 0 or args.delay > 60:
        problem = "--delay is 0 to 60 seconds"
    elif not 0 < args.timeout <= 60:
        problem = "--timeout is more than 0 and at most 60 seconds"
    if problem:
        print("check_links.py: " + problem, file=sys.stderr)
        return finish(False, [], [], problem, 2)
    visitor = visitor or Visitor(args.delay, args.timeout)
    reports = []
    for url in urls:
        report = check_link(url, visitor)
        reports.append(report)
        print("%s  %s  %s" % (report["status"] if report["status"] is not None else "---", url, report["problem"] or "opens"),
              file=sys.stderr)
    outputs = []
    try:
        if args.json_out:
            outputs.append(write_report(args.json_out, json.dumps(reports, ensure_ascii=False, indent=2) + "\n"))
        if args.markdown_out:
            outputs.append(write_report(args.markdown_out, markdown_table(reports)))
    except OSError as error:
        message = "can't write a report: %s" % (error.strerror or type(error).__name__)
        print("check_links.py: " + message, file=sys.stderr)
        return finish(False, outputs, [], message, 2)
    checks = [{"url": r["url"], "status": r["status"], "ok": r["ok"]} for r in reports]
    return finish(True, outputs, checks, None, 0)


if __name__ == "__main__":
    sys.exit(main())
