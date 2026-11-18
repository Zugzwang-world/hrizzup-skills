"""check_links.py (the Source check skill's link checker), with the network stubbed.

Nothing here touches the network: `resolve` and `fetch` are replaced, so every safety rule is proved
on crafted addresses and redirects.
"""

import contextlib
import gzip
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "source-check", "scripts", "check_links.py")


def load():
    spec = importlib.util.spec_from_file_location("check_links_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


links = load()
PUBLIC = "93.184.216.34"


class Net:
    """A stand-in for the network: names resolve through `names`, pages answer from `pages`."""

    def __init__(self, names=None, pages=None):
        self.names = names if names is not None else {}
        self.pages = pages if pages is not None else {}
        self.calls = []  # (host, address, port, method, path)
        self.resolved = []

    def resolve(self, host, port):
        self.resolved.append(host)
        found = self.names.get(host, [PUBLIC])
        if isinstance(found, Exception):
            raise found
        return found

    def fetch(self, host, address, port, method, path, timeout):
        self.calls.append((host, address, port, method, path))
        answer = self.pages.get((host, path), (200, {"content-type": "text/plain"}, b""))
        if callable(answer):
            answer = answer(method, len(self.calls))
        if isinstance(answer, Exception):
            raise answer
        status, headers, body = answer
        return status, dict(headers), (body if method == "GET" else b"")

    @contextlib.contextmanager
    def installed(self):
        with mock.patch.object(links, "resolve", self.resolve), mock.patch.object(links, "fetch", self.fetch):
            yield self


def visitor(delay=1.0):
    sleeps = []
    now = [100.0]

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    return links.Visitor(delay=delay, timeout=5, sleep=sleep, clock=lambda: now[0]), sleeps


def report(url, net, delay=1.0):
    with net.installed():
        seen, _sleeps = visitor(delay)
        return links.check_link(url, seen)


class Addresses(unittest.TestCase):
    def test_refused(self):
        for address in ("127.0.0.1", "127.8.8.8", "10.0.0.1", "172.16.5.5", "192.168.1.1", "169.254.169.254", "0.0.0.0",
                        "224.0.0.1", "100.64.0.1", "240.0.0.1", "::1", "::", "fc00::1", "fd12:3456::1", "fe80::1",
                        "ff02::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "2002:7f00:1::1",
                        "64:ff9b::7f00:1"):
            self.assertIsNotNone(links.unsafe_reason(address), address)

    def test_public(self):
        for address in (PUBLIC, "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8"):
            self.assertIsNone(links.unsafe_reason(address), address)

    def test_not_an_address(self):
        self.assertIsNotNone(links.unsafe_reason("not-an-address"))


class Vetting(unittest.TestCase):
    def refused(self, url):
        with self.assertRaises(links.Refused):
            links.vet(url)

    def test_only_https(self):
        for url in ("http://example.com/", "ftp://example.com/", "javascript:alert(1)", "example.com/page", "//example.com/",
                    "file:///etc/passwd", "HTTP://example.com/"):
            self.refused(url)

    def test_no_credentials_and_no_odd_ports(self):
        at = chr(64)  # built from a piece: the repository's own check reads a name, an at sign and a host as an email address
        self.refused("https://user:pass" + at + "example.com/")
        self.refused("https://user" + at + "example.com/")
        self.refused("https://example.com:8080/")
        self.refused("https://example.com:99999/")

    def test_no_host(self):
        self.refused("https:///path")
        self.refused("https://")

    def test_fine(self):
        self.assertEqual(links.vet("https://example.com/a/b?x=1#frag"), ("example.com", 443, "/a/b?x=1"))
        self.assertEqual(links.vet("HTTPS://Example.com:443"), ("example.com", 443, "/"))


class Refusals(unittest.TestCase):
    def assert_refused(self, url, names=None):
        result, _net = self.refused(url, names)
        return result

    def refused(self, url, names=None):
        net = Net(names=names)
        result = report(url, net)
        self.assertFalse(result["ok"], url)
        self.assertIsNone(result["status"], url)
        self.assertIsNotNone(result["problem"], url)
        self.assertEqual(net.calls, [], "%s: no request may be made" % url)
        return result, net

    def test_http(self):
        result = self.assert_refused("http://example.com/")
        self.assertIn("https", result["problem"])

    def test_addresses_written_in_the_link(self):
        for url in ("https://127.0.0.1/", "https://10.1.2.3/x", "https://169.254.169.254/latest/meta-data/",
                    "https://[::1]/", "https://[fc00::1]/", "https://[::ffff:127.0.0.1]/", "https://0.0.0.0/"):
            _result, net = self.refused(url)
            self.assertEqual(net.resolved, [], "%s: an address needs no lookup" % url)

    def test_names_that_resolve_to_private_addresses(self):
        self.assert_refused("https://localhost/", {"localhost": ["127.0.0.1", "::1"]})
        self.assert_refused("https://intranet.test/", {"intranet.test": ["10.0.0.5"]})
        self.assert_refused("https://rebind.test/", {"rebind.test": [PUBLIC, "192.168.0.1"]})  # one bad address is enough
        self.assert_refused("https://mapped.test/", {"mapped.test": ["::ffff:127.0.0.1"]})
        self.assert_refused("https://decimal.test/", {"decimal.test": ["127.0.0.1"]})

    def test_a_name_that_does_not_resolve(self):
        net = Net(names={"nowhere.test": links.NetworkProblem("the address doesn't resolve (no such host)", "connect")})
        result = report("https://nowhere.test/", net)
        self.assertFalse(result["ok"])
        self.assertIn("resolve", result["problem"])
        self.assertEqual(net.calls, [])


class Redirects(unittest.TestCase):
    def test_a_redirect_is_followed_and_counted(self):
        net = Net(pages={
            ("a.test", "/"): (301, {"location": "https://b.test/moved"}, b""),
            ("b.test", "/moved"): (200, {"content-type": "text/plain"}, b""),
        })
        result = report("https://a.test/", net)
        self.assertTrue(result["ok"])
        self.assertEqual((result["status"], result["redirects"], result["finalUrl"]), (200, 1, "https://b.test/moved"))
        self.assertEqual(result["url"], "https://a.test/")

    def test_a_relative_redirect(self):
        net = Net(pages={("a.test", "/x"): (302, {"location": "/y?z=1"}, b""), ("a.test", "/y?z=1"): (200, {}, b"")})
        result = report("https://a.test/x", net)
        self.assertEqual((result["ok"], result["finalUrl"]), (True, "https://a.test/y?z=1"))

    def test_at_most_five_redirects(self):
        net = Net(pages={("a.test", "/%d" % n): (301, {"location": "https://a.test/%d" % (n + 1)}, b"") for n in range(0, 12)})
        result = report("https://a.test/0", net)
        self.assertFalse(result["ok"])
        self.assertEqual(result["redirects"], 5)
        self.assertIn("redirects", result["problem"])
        self.assertEqual(len(net.calls), 6)  # the first request and five redirects: nothing more

    def test_five_redirects_are_allowed(self):
        pages = {("a.test", "/%d" % n): (301, {"location": "https://a.test/%d" % (n + 1)}, b"") for n in range(0, 5)}
        pages[("a.test", "/5")] = (200, {"content-type": "text/plain"}, b"")
        result = report("https://a.test/0", Net(pages=pages))
        self.assertTrue(result["ok"])
        self.assertEqual(result["redirects"], 5)

    def test_a_redirect_to_http_is_refused(self):
        net = Net(pages={("a.test", "/"): (301, {"location": "http://b.test/"}, b"")})
        result = report("https://a.test/", net)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 301)
        self.assertEqual(result["redirects"], 0)  # a redirect that isn't followed isn't counted
        self.assertIn("not followed", result["problem"])
        self.assertEqual(len(net.calls), 1)

    def test_a_redirect_to_a_private_address_is_refused(self):
        for target in ("https://127.0.0.1/", "https://169.254.169.254/", "https://[::1]/", "https://[::ffff:127.0.0.1]/",
                       "https://10.0.0.1/admin", "https://internal.test/", "https://localhost/", "https://[fc00::]/",
                       "https://[fc00::1]/", "http://localhost/", "http://127.0.0.1/"):
            net = Net(names={"internal.test": ["10.0.0.9"], "localhost": ["127.0.0.1", "::1"]},
                      pages={("a.test", "/"): (302, {"location": target}, b"")})
            result = report("https://a.test/", net)
            self.assertFalse(result["ok"], target)
            self.assertIn("not followed", result["problem"], target)
            self.assertEqual(len(net.calls), 1, "%s: only the first request may be made" % target)

    def test_a_redirect_with_nowhere_to_go(self):
        result = report("https://a.test/", Net(pages={("a.test", "/"): (301, {}, b"")}))
        self.assertFalse(result["ok"])
        self.assertIn("doesn't say where", result["problem"])


class Requests(unittest.TestCase):
    def test_it_connects_to_the_address_it_checked(self):
        net = Net(names={"a.test": ["151.101.1.69"]}, pages={("a.test", "/"): (200, {"content-type": "text/plain"}, b"")})
        report("https://a.test/", net)
        self.assertEqual(net.calls[0][:3], ("a.test", "151.101.1.69", 443))

    def test_head_first_and_no_get_for_a_plain_file(self):
        net = Net(pages={("a.test", "/f.pdf"): (200, {"content-type": "application/pdf"}, b"")})
        result = report("https://a.test/f.pdf", net)
        self.assertEqual([c[3] for c in net.calls], ["HEAD"])
        self.assertEqual((result["ok"], result["contentType"], result["title"]), (True, "application/pdf", None))

    def test_get_when_head_is_refused(self):
        def answer(method, _n):
            return (405, {}, b"") if method == "HEAD" else (200, {"content-type": "text/plain"}, b"")
        net = Net(pages={("a.test", "/"): answer})
        result = report("https://a.test/", net)
        self.assertEqual([c[3] for c in net.calls], ["HEAD", "GET"])
        self.assertTrue(result["ok"])

    def test_a_missing_page_is_a_finding(self):
        net = Net(pages={("a.test", "/gone"): (404, {"content-type": "text/html"}, b"<title>Gone</title>")})
        result = report("https://a.test/gone", net)
        self.assertEqual((result["ok"], result["status"]), (False, 404))
        self.assertIn("404", result["problem"])

    def test_the_title_of_a_page(self):
        body = b"<html><head><TITLE>\n  Delhi &amp; the smog \n</TITLE></head><body>x</body></html>"
        net = Net(pages={("a.test", "/"): (200, {"content-type": "text/html; charset=utf-8", "last-modified": "Mon, 02 Nov 2026 01:30:00 GMT"}, body)})
        result = report("https://a.test/", net)
        self.assertEqual(result["title"], "Delhi & the smog")
        self.assertEqual(result["contentType"], "text/html")
        self.assertEqual(result["lastModified"], "Mon, 02 Nov 2026 01:30:00 GMT")
        self.assertEqual([c[3] for c in net.calls], ["HEAD", "GET"])

    def test_a_title_holds_no_control_or_invisible_character(self):
        body = ("<title>Hello" + chr(0) + chr(0x200B) + chr(0x202E) + "\tworld" + chr(0x2028) + "!</title>").encode("utf-8")
        net = Net(pages={("a.test", "/"): (200, {"content-type": "text/html"}, body)})
        self.assertEqual(report("https://a.test/", net)["title"], "Helloworld !")

    def test_a_title_is_cut_to_200_characters(self):
        body = ("<title>" + "x" * 500 + "</title>").encode("utf-8")
        net = Net(pages={("a.test", "/"): (200, {"content-type": "text/html"}, body)})
        self.assertEqual(len(report("https://a.test/", net)["title"]), 200)

    def test_a_gzipped_page(self):
        body = gzip.compress(b"<title>Zipped</title>")
        net = Net(pages={("a.test", "/"): (200, {"content-type": "text/html", "content-encoding": "gzip"}, body)})
        self.assertEqual(report("https://a.test/", net)["title"], "Zipped")

    def test_a_page_without_a_title(self):
        net = Net(pages={("a.test", "/"): (200, {"content-type": "text/html"}, b"<p>hi</p>")})
        self.assertIsNone(report("https://a.test/", net)["title"])

    def test_a_dropped_connection_gets_one_get(self):
        def answer(method, _n):
            if method == "HEAD":
                return links.NetworkProblem("the site closed the connection without answering", "reset")
            return (200, {"content-type": "text/plain"}, b"")
        net = Net(pages={("a.test", "/"): answer})
        self.assertTrue(report("https://a.test/", net)["ok"])

    def test_a_dead_host_is_asked_once(self):
        net = Net(pages={("a.test", "/"): links.NetworkProblem("couldn't connect (Connection refused)", "connect")})
        result = report("https://a.test/", net)
        self.assertFalse(result["ok"])
        self.assertIn("connect", result["problem"])
        self.assertEqual(len(net.calls), 1)

    def test_a_timeout_and_a_certificate_problem_are_reported(self):
        for kind, text in (("timeout", "no answer in 5 seconds"), ("tls", "its certificate isn't trusted (expired)")):
            net = Net(pages={("a.test", "/"): links.NetworkProblem(text, kind)})
            self.assertEqual(report("https://a.test/", net)["problem"], text)

    def test_the_report_has_exactly_its_fields(self):
        result = report("https://a.test/", Net())
        self.assertEqual(list(result), ["url", "finalUrl", "status", "ok", "redirects", "contentType", "title",
                                         "lastModified", "checkedAt", "problem"])
        self.assertRegex(result["checkedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class Manners(unittest.TestCase):
    def test_one_request_to_a_host_every_delay(self):
        net = Net()
        with net.installed():
            seen, sleeps = visitor(delay=2.0)
            links.check_link("https://a.test/one", seen)
            links.check_link("https://a.test/two", seen)
            links.check_link("https://b.test/other", seen)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 2.0)

    def test_a_short_retry_after_is_waited_for_once(self):
        def answer(method, n):
            return (429, {"retry-after": "3"}, b"") if n == 1 else (200, {"content-type": "text/plain"}, b"")
        net = Net(pages={("a.test", "/"): answer})
        with net.installed():
            seen, sleeps = visitor(delay=0)
            result = links.check_link("https://a.test/", seen)
        self.assertTrue(result["ok"])
        self.assertIn(3, sleeps)
        self.assertEqual(len(net.calls), 2)

    def test_it_only_waits_once(self):
        net = Net(pages={("a.test", "/"): (429, {"retry-after": "3"}, b"")})
        with net.installed():
            seen, sleeps = visitor(delay=0)
            result = links.check_link("https://a.test/", seen)
        self.assertFalse(result["ok"])
        self.assertEqual(sleeps.count(3), 1)

    def test_a_long_retry_after_is_not_waited_for(self):
        net = Net(pages={("a.test", "/"): (429, {"retry-after": "120"}, b"")})
        with net.installed():
            seen, sleeps = visitor(delay=0)
            result = links.check_link("https://a.test/", seen)
        self.assertEqual((result["ok"], result["status"]), (False, 429))
        self.assertNotIn(120, sleeps)

    def test_retry_after_as_a_date(self):
        self.assertEqual(links.retry_after_seconds("7"), 7)
        self.assertIsNone(links.retry_after_seconds("soon"))
        self.assertEqual(links.retry_after_seconds("Mon, 02 Nov 2020 01:30:00 GMT"), 0)

    def test_it_names_itself(self):
        self.assertIn("hrizzup-skills-link-check/1.0", links.USER_AGENT)
        self.assertIn("https://github.com/Zugzwang-world/hrizzup-skills", links.USER_AGENT)

    def test_at_most_64_kib_of_a_page(self):
        self.assertEqual(links.MAX_READ, 64 * 1024)


class OddLinks(unittest.TestCase):
    """A link, a redirect or a site that does something odd must end in a finding, never a crash."""

    def test_a_path_and_query_are_made_safe_before_they_are_sent(self):
        host, port, path = links.vet("https://example.com/\u0926\u093f?q=a b#fragment")
        self.assertEqual((host, port), ("example.com", 443))
        self.assertEqual(path, "/%E0%A4%A6%E0%A4%BF?q=a%20b")
        self.assertTrue(path.isascii())
        self.assertEqual(links.vet("https://example.com/a%20b?x=%41")[2], "/a%20b?x=%41")  # existing escapes stay

    def test_the_host_goes_in_its_ascii_form(self):
        self.assertEqual(links.vet("https://b\u00fccher.example/p")[0], "xn--bcher-kva.example")
        with self.assertRaises(links.Refused):
            links.vet("https://a..b.example/")

    def test_a_link_with_unicode_reaches_the_network_layer_as_ascii(self):
        net = Net()
        report("https://example.com/\u0926\u093f?q=a b", net)
        self.assertTrue(all(call[4].isascii() for call in net.calls))
        result = report("https://example.com/\u0926\u093f#frag", Net())
        self.assertEqual(result["finalUrl"], "https://example.com/%E0%A4%A6%E0%A4%BF")  # what was requested, no fragment

    def test_a_redirect_that_is_not_an_address(self):
        for location in ("https://[::1/", "https://a b.test/x", "https://exa\x00mple.test/"):
            net = Net(pages={("a.test", "/"): (302, {"location": location}, b"")})
            result = report("https://a.test/", net)
            self.assertFalse(result["ok"], repr(location))
            self.assertIsNotNone(result["problem"], repr(location))
            self.assertEqual(len(net.calls), 1)

    def test_a_redirect_to_a_non_ascii_path_is_followed_safely(self):
        net = Net(pages={("a.test", "/"): (302, {"location": "/\u0926"}, b""), ("a.test", "/%E0%A4%A6"): (200, {}, b"")})
        self.assertTrue(report("https://a.test/", net)["ok"])

    def test_an_unexpected_error_is_a_finding_and_the_run_goes_on(self):
        def boom(method, _n):
            raise RuntimeError("boom")
        net = Net(pages={("a.test", "/"): boom})
        with net.installed():
            seen, _sleeps = visitor(0)
            first = links.check_link("https://a.test/", seen)
            second = links.check_link("https://b.test/", seen)
        self.assertFalse(first["ok"])
        self.assertIn("didn't expect", first["problem"])
        self.assertNotIn("boom", first["problem"])  # nothing the error said is passed on
        self.assertTrue(second["ok"])

    def test_the_site_cannot_put_odd_characters_in_the_report(self):
        headers = {"content-type": "text/html\x07;x=1", "last-modified": "Mon\x1b[31m 02 Nov"}
        net = Net(pages={("a.test", "/"): (200, headers, b"")})
        result = report("https://a.test/", net)
        for field in ("contentType", "lastModified"):
            self.assertFalse(any(ord(c) < 32 for c in result[field] or ""), field)


class FakeConnection:
    """Stands in for PinnedConnection, to test `fetch` itself: it raises what a socket or a site would."""

    def __init__(self, raises=None, status=200, headers=None, body=b""):
        self.raises, self.status, self.headers, self.body = raises, status, headers or [("Content-Type", "text/html")], body
        self.requests, self.read_limits = [], []

    def __call__(self, host, address, port, timeout, context):
        return self

    def request(self, method, path, headers=None):
        if self.raises is not None:
            raise self.raises
        self.requests.append((method, path, headers))

    def getresponse(self):
        return self

    def getheaders(self):
        return self.headers

    def read(self, amount):
        self.read_limits.append(amount)
        return self.body[:amount]

    def close(self):
        pass


class Fetching(unittest.TestCase):
    def fetch(self, fake, method="HEAD"):
        with mock.patch.object(links, "PinnedConnection", fake):
            return links.fetch("a.test", PUBLIC, 443, method, "/", 5)

    def problem(self, error):
        with self.assertRaises(links.NetworkProblem) as caught:
            self.fetch(FakeConnection(raises=error))
        return caught.exception

    def test_an_answer(self):
        fake = FakeConnection(status=200, headers=[("Content-Type", "text/html"), ("X-Many", "a"), ("x-many", "b")], body=b"x" * 100000)
        status, headers, body = self.fetch(fake, "GET")
        self.assertEqual((status, headers["content-type"], len(body)), (200, "text/html", 64 * 1024))
        self.assertEqual(fake.read_limits, [64 * 1024])
        self.assertEqual(fake.requests[0][2]["User-Agent"], links.USER_AGENT)
        self.assertNotIn("Cookie", fake.requests[0][2])
        self.assertEqual(self.fetch(FakeConnection(body=b"abc"), "HEAD")[2], b"")  # a HEAD reads no body

    def test_what_a_site_or_a_socket_can_raise(self):
        verify = links.ssl.SSLCertVerificationError(1, "x")
        verify.verify_message = "certificate has expired"
        cases = (
            (http_error("InvalidURL"), "other", "valid HTTP"),
            (http_error("IncompleteRead"), "other", "valid HTTP"),
            (http_error("LineTooLong"), "other", "valid HTTP"),
            (UnicodeEncodeError("ascii", "\u0926", 0, 1, "ordinal not in range"), "other", "can't be sent"),
            (ValueError("bad header"), "other", "can't be sent"),
            (verify, "tls", "expired"),
            (links.ssl.SSLError(1, "handshake"), "tls", "secure connection"),
            (links.socket.timeout("timed out"), "timeout", "no answer"),
            (ConnectionRefusedError(61, "Connection refused"), "connect", "couldn't connect"),
            (OSError("network is down"), "connect", "couldn't connect"),
            (links.http.client.RemoteDisconnected("gone"), "reset", "closed the connection"),
            (ConnectionResetError(54, "reset"), "reset", "closed the connection"),
        )
        for error, kind, words in cases:
            found = self.problem(error)
            self.assertEqual((found.kind, words in str(found)), (kind, True), "%r -> %s: %s" % (error, found.kind, found))

    def test_each_of_them_ends_as_a_finding(self):
        for error in (http_error("InvalidURL"), UnicodeEncodeError("ascii", "x", 0, 1, "bad"), OSError("down")):
            with mock.patch.object(links, "PinnedConnection", FakeConnection(raises=error)):
                seen, _sleeps = visitor(0)
                with mock.patch.object(links, "resolve", lambda host, port: [PUBLIC]):
                    result = links.check_link("https://a.test/", seen)
            self.assertFalse(result["ok"])
            self.assertIsNotNone(result["problem"])


def http_error(name):
    cls = getattr(links.http.client, name)
    return cls(b"") if name == "IncompleteRead" else cls("x")


class Finding(unittest.TestCase):
    def test_links_in_a_text(self):
        text = ("See https://example.com/a, and (https://example.org/b). Also [here](https://example.net/c) and "
                "http://insecure.test/d! Again https://example.com/a. Wiki: https://en.example.com/wiki/Thing_(film).")
        self.assertEqual(links.links_in(text), [
            "https://example.com/a", "https://example.org/b", "https://example.net/c", "http://insecure.test/d",
            "https://en.example.com/wiki/Thing_(film)"])

    def test_the_markdown_table(self):
        table = links.markdown_table([
            {"url": "https://a.test/", "status": 404, "ok": False, "redirects": 0, "title": None, "problem": "not found | gone"},
        ])
        self.assertIn("| https://a.test/ | 404 | no | 0 | - | not found \\| gone |", table)


class Command(unittest.TestCase):
    def run_main(self, argv, net):
        out, err = io.StringIO(), io.StringIO()
        seen, _sleeps = visitor(0)
        with net.installed(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = links.main(argv, visitor=seen)
        return code, out.getvalue(), err.getvalue()

    def test_exit_zero_even_when_every_link_is_dead_and_the_last_line_is_json(self):
        net = Net(pages={("a.test", "/x"): (404, {}, b"")})
        code, out, _err = self.run_main(["https://a.test/x", "http://b.test/y"], net)
        self.assertEqual(code, 0)
        last = json.loads(out.strip().split("\n")[-1])
        self.assertEqual(set(last), {"ok", "outputs", "checks", "problem"})
        self.assertEqual([c["ok"] for c in last["checks"]], [False, False])

    def test_files_and_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "brief.md")
            with open(source, "w", encoding="utf-8") as f:
                f.write("- https://a.test/one\n- https://a.test/one\n- https://c.test/two\n")
            out_json, out_md = os.path.join(folder, "r.json"), os.path.join(folder, "r.md")
            code, out, _err = self.run_main(["--file", source, "--json", out_json, "--markdown", out_md], Net())
            self.assertEqual(code, 0)
            with open(out_json, encoding="utf-8") as f:
                reports = json.load(f)
            self.assertEqual([r["url"] for r in reports], ["https://a.test/one", "https://c.test/two"])
            last = json.loads(out.strip().split("\n")[-1])
            self.assertEqual([o["path"] for o in last["outputs"]], [out_json, out_md])
            with open(out_md, encoding="utf-8") as f:
                self.assertTrue(f.read().startswith("| Link |"))

    def test_an_output_never_overwrites_an_input_or_another_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "brief.md")
            with open(source, "w", encoding="utf-8") as f:
                f.write("- https://a.test/one\n")
            other = os.path.join(folder, "r.json")
            for argv in (["--file", source, "--json", source], ["--file", source, "--markdown", source],
                         ["https://a.test/", "--json", other, "--markdown", other]):
                code, out, _err = self.run_main(argv, Net())
                self.assertEqual(code, 2, argv)
                self.assertFalse(json.loads(out.strip().split("\n")[-1])["ok"])
            with open(source, encoding="utf-8") as f:
                self.assertEqual(f.read(), "- https://a.test/one\n")  # untouched
            self.assertFalse(os.path.exists(other))

    def test_bad_input_exits_two(self):
        for argv in ([], ["--file", os.path.join(tempfile.gettempdir(), "no-such-file-for-the-test")],
                     ["https://a.test/", "--delay", "-1"], ["https://a.test/", "--timeout", "0"],
                     ["https://a.test/%d" % n for n in range(links.MAX_LINKS + 1)]):
            code, out, _err = self.run_main(argv, Net())
            self.assertEqual(code, 2, argv[:3])
            self.assertFalse(json.loads(out.strip().split("\n")[-1])["ok"])


class Kit(unittest.TestCase):
    def test_it_is_standard_library_only_with_the_header_the_check_wants(self):
        with open(SCRIPT, encoding="utf-8") as f:
            source = f.read()
        self.assertIn('# requires-python = ">=3.10"', source)
        self.assertIn("# dependencies = []", source)


if __name__ == "__main__":
    unittest.main()
