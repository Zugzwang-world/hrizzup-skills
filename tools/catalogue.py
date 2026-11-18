#!/usr/bin/env python3
"""Hrizzup's skills repository: make the generated files, and check everything (docs/design.md).

    python3.12 tools/catalogue.py write                 # make the generated files
    python3.12 tools/catalogue.py check [--base <sha>]  # every rule; exit 1 with the problems
    python3.12 tools/catalogue.py hash <folder>         # a skill's or agent's contentHash

Standard library only, offline, Python 3.12 or later (this Mac's `python3` is older: use
`python3.12`, or `uv run tools/catalogue.py`). `check` prints `path: rule: message` for each
problem. `write` makes, in this order: the shared copies in each skill, each SKILL.md's and
AGENT.md's generated sections, the README's table and catalogue.json.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 12):
    sys.stderr.write(
        "catalogue.py needs Python 3.12 or later (this is %d.%d). Run it as `python3.12 tools/catalogue.py ...` "
        "or `uv run tools/catalogue.py ...`.\n" % sys.version_info[:2]
    )
    raise SystemExit(2)

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tomllib
import unicodedata
from pathlib import Path

import frontmatter
import rules

ROOT = Path(__file__).resolve().parent.parent
RULE = "run `python3.12 tools/catalogue.py write`"
BOM = chr(0xFEFF)  # the byte-order mark, built so this file holds no invisible character


def _load_media():
    """The standard-library part of the shared media module, from this repository."""
    spec = importlib.util.spec_from_file_location("hrizzup_media", ROOT / "shared" / "scripts" / "hrizzup_media.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hrizzup_media"] = module
    spec.loader.exec_module(module)
    return module


media = _load_media()


# ---------------------------------------------------------------------------------------------
# The tree: the files that are (or would be) in a pull request, plus what `write` would change
# ---------------------------------------------------------------------------------------------

class Problems:
    """What `check` found: (path, rule, message), printed as `path: rule: message`."""

    def __init__(self):
        self.items = []

    def add(self, path, rule, message):
        self.items.append((str(path), rule, message))

    def lines(self):
        return ["%s: %s: %s" % item for item in sorted(set(self.items))]

    def __len__(self):
        return len(set(self.items))


class Tree:
    def __init__(self, root):
        self.root = Path(root)
        self.overrides = {}
        self._listing = None
        self.symlinks = set()

    def files(self):
        """Every file's path from the root, with `/`, sorted; overrides included."""
        if self._listing is None:
            self._listing = self._list()
        return sorted(set(self._listing) | set(self.overrides))

    def _list(self):
        names = None
        if (self.root / ".git").exists():
            try:
                out = subprocess.run(
                    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                    cwd=self.root, capture_output=True, check=True, timeout=120,
                ).stdout
                names = [n for n in out.decode("utf-8", "surrogateescape").split("\0") if n]
            except (OSError, subprocess.SubprocessError):
                names = None
        if names is None:
            names = []
            for folder, dirs, files in os.walk(self.root):
                dirs[:] = sorted(d for d in dirs if d not in rules.IGNORED_NAMES)
                for d in list(dirs):
                    if os.path.islink(os.path.join(folder, d)):  # a link to a folder counts as a file
                        files.append(d)
                        dirs.remove(d)
                for name in files:
                    if name in rules.IGNORED_NAMES or name.endswith(".pyc"):
                        continue
                    names.append(os.path.relpath(os.path.join(folder, name), self.root).replace(os.sep, "/"))
        kept = []
        for name in names:
            link = self.first_link(name)
            if link is not None:  # a link, or something below a linked folder: never read or written
                self.symlinks.add(link)
                continue
            if os.path.isfile(os.path.join(self.root, name)) and not self.outside(name):
                kept.append(name)
        return kept

    def first_link(self, rel):
        """The shortest prefix of `rel` below the root that is a symbolic link, or None."""
        current = self.root
        parts = rel.split("/")
        for number, part in enumerate(parts):
            current = current / part
            if os.path.islink(current):
                return "/".join(parts[:number + 1])
            if not os.path.lexists(current):
                return None
        return None

    def outside(self, rel):
        """Whether `rel` resolves to somewhere outside the root (a backstop for first_link)."""
        root = os.path.realpath(self.root)
        return os.path.commonpath([root, os.path.realpath(self.root / rel)]) != root

    @staticmethod
    def plain_path(rel):
        """Whether `rel` is a clean path from the root: `/`-separated names, none empty, `.` or `..`."""
        return isinstance(rel, str) and "\\" not in rel and "\0" not in rel and all(
            part not in ("", ".", "..") for part in rel.split("/"))

    def exists(self, rel):
        if rel in self.overrides:
            return True
        if not self.plain_path(rel) or self.first_link(rel) is not None or self.outside(rel):
            return False
        return os.path.isfile(self.root / rel)

    def _refuse_links(self, rel):
        if not self.plain_path(rel):
            raise OSError("refusing a path with `.`, `..` or an empty part: %r" % (rel,))
        if self.first_link(rel) is not None or self.outside(rel):
            raise OSError("refusing to go through a symbolic link: %s" % rel)

    def read(self, rel):
        if rel in self.overrides:
            return self.overrides[rel]
        self._refuse_links(rel)
        with open(self.root / rel, "rb") as f:
            return f.read()

    def text(self, rel):
        """The file as text, or None if it isn't UTF-8."""
        try:
            return self.read(rel).decode("utf-8")
        except UnicodeDecodeError:
            return None

    def size(self, rel):
        if rel in self.overrides:
            return len(self.overrides[rel])
        self._refuse_links(rel)
        return os.path.getsize(self.root / rel)

    def put(self, rel, data):
        self.overrides[rel] = data if isinstance(data, bytes) else data.encode("utf-8")

    def changed(self):
        """The overrides that differ from what's on disk."""
        found = {}
        for rel, data in self.overrides.items():
            path = self.root / rel
            if self.first_link(rel) is not None or not path.is_file() or path.read_bytes() != data:
                found[rel] = data
        return found

    def write_all(self, changed):
        """Write the changed files, after checking every target stays inside the root. Returns problems."""
        problems = []
        for rel in sorted(changed):
            if self.first_link(rel) is not None or self.outside(rel):
                problems.append("%s: paths: a symbolic link in the way: nothing was written" % rel)
        if problems:
            return problems
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        for rel, data in sorted(changed.items()):
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if self.outside(rel):
                return ["%s: paths: resolves outside the repository: stopped" % rel]
            with os.fdopen(os.open(str(target), flags, 0o644), "wb") as f:
                f.write(data)
        return []

    def folder(self, prefix):
        """Paths under a folder, relative to it."""
        prefix = prefix.rstrip("/") + "/"
        return [p[len(prefix):] for p in self.files() if p.startswith(prefix)]


# ---------------------------------------------------------------------------------------------
# Text rules (4.2) and the public-repository rules
# ---------------------------------------------------------------------------------------------

def is_text_file(rel):
    name = rel.rsplit("/", 1)[-1]
    if name in (".gitattributes", ".gitignore"):
        return True
    return name.endswith(rules.TEXT_EXTENSIONS)


def catalogue_text_problems(text):
    """Why text can't be a SKILL.md or AGENT.md (4.2): [] when it can."""
    found = []
    if "\r" in text:
        found.append("a carriage return: lines end with LF only")
    bad = sorted({c for c in text if not rules.catalogue_char_ok(c, newline=True)})
    if bad:
        found.append("characters catalogue text can't hold: " + " ".join("U+%04X" % ord(c) for c in bad[:10]))
    if not text.endswith("\n"):
        found.append("no final new line")
    elif text.endswith("\n\n"):
        found.append("more than one final new line")
    for number, line in enumerate(text.split("\n"), start=1):
        if line != line.rstrip(" "):
            found.append("line %d ends with a space" % number)
            break
    return found


def check_text_file(rel, data, P):
    """UTF-8, no BOM, LF, one final LF, no hidden characters, nothing private (4.2, 7.2.8, 7.2.9)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        P.add(rel, "text", "not UTF-8 (byte %d)" % error.start)
        return
    licence = rel.rsplit("/", 1)[-1] == rules.LICENCE_FILE
    if text.startswith(BOM):
        P.add(rel, "text", "starts with a byte-order mark")
    check = text.replace("\r\n", "\n") if licence else text
    if "\r" in check:
        P.add(rel, "text", "has a carriage return: lines end with LF only")
    if text and not licence:
        if not text.endswith("\n"):
            P.add(rel, "text", "no final new line")
        elif text.endswith("\n\n"):
            P.add(rel, "text", "more than one final new line")
    body = check[1:] if text.startswith(BOM) else check  # a leading BOM is reported once, above
    bad = sorted({c for c in body if c not in "\n\t" and unicodedata.category(c) in rules.BAD_CATEGORIES})
    if bad:
        P.add(rel, "text", "has hidden or control characters: " + " ".join("U+%04X" % ord(c) for c in bad[:10]))
    if rules.HOME_PATH.search(text):
        P.add(rel, "public", "holds a home-folder path: the repository is public")
    for email in rules.EMAIL.findall(text):
        if not email.endswith(rules.NOREPLY_SUFFIX):
            P.add(rel, "public", "holds an email address (only GitHub's noreply ones may be written here)")
            break
    if rules.DIGEST_TRAP.search(text):
        P.add(rel, "digest", "a digest sits where the Secret check would read it as a key: put the digest first "
                              "in a tuple or a table, or in the lock (docs/design.md, 5, Digests)")


# ---------------------------------------------------------------------------------------------
# The layout (3)
# ---------------------------------------------------------------------------------------------

def norm_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def allowed_in_folder(folder, rest):
    """Whether `rest` (a path inside a skill's or shared folder) has a type that folder may hold."""
    name = rest.rsplit("/", 1)[-1]
    if folder == "assets" and name.endswith(".txt"):
        return name == rules.LICENCE_FILE
    if folder == "scripts" and "/" in rest:
        return False
    return name.endswith(rules.SKILL_FOLDERS[folder])


def check_layout(tree, P):
    files = tree.files()
    lowered = {}
    for rel in files:
        parts = rel.split("/")
        lowered.setdefault(rel.lower(), []).append(rel)
        if len(rel) > rules.PATH_MAX:
            P.add(rel, "paths", "longer than %d characters" % rules.PATH_MAX)
        for number, part in enumerate(parts):
            exempt = number == 0 and part in rules.TOP_LEVEL_DOT
            if not exempt and not rules.PATH_PART.match(part):
                P.add(rel, "paths", "%r: use letters, digits, `.`, `_` and `-`, starting with a letter or digit" % part)
            low = part.lower()
            hit = [w for w in rules.DIGEST_WORDS if w in low]
            if hit:
                P.add(rel, "digest", "%r holds %r, which the Secret check reads as a key's name: rename it" % (part, hit[0]))
        if rel not in tree.overrides and tree.size(rel) > rules.FILE_MAX_BYTES:
            P.add(rel, "paths", "over %d MiB" % (rules.FILE_MAX_BYTES // (1024 * 1024)))
        top = parts[0]
        if top not in rules.TOP_LEVEL:
            P.add(rel, "layout", "%r isn't a top-level name the repository allows" % top)
        elif len(parts) == 1 and top in ("docs", "shared", "skills", "agents", "tools", ".github"):
            P.add(rel, "layout", "%r must be a folder" % top)
        elif len(parts) > 1 and top not in ("docs", "shared", "skills", "agents", "tools", ".github"):
            P.add(rel, "layout", "%r is a file, not a folder" % top)
    for link in sorted(tree.symlinks):
        P.add(link, "paths", "a symbolic link (or a folder that is one): raw downloads would get the link's text, "
                             "and `write` never follows one")
    for same in lowered.values():
        if len(same) > 1:
            P.add(same[0], "paths", "differs only in case from %s" % ", ".join(same[1:]))
    gitattributes = tree.text(".gitattributes") if tree.exists(".gitattributes") else None
    if gitattributes is None or gitattributes.split("\n", 1)[0] != "* -text":
        P.add(".gitattributes", "layout", "its first line must be `* -text`, so git never rewrites a byte")
    gitignore = tree.text(".gitignore") if tree.exists(".gitignore") else None
    if gitignore is None or not set(rules.GITIGNORE_LINES) <= set(gitignore.split("\n")):
        P.add(".gitignore", "layout", "must name " + ", ".join(rules.GITIGNORE_LINES))
    for needed in ("README.md", "NOTICES.md", "retired.txt", "catalogue.json"):
        if not tree.exists(needed):
            P.add(needed, "layout", "missing")

    for rel in files:
        parts = rel.split("/")
        if parts[0] == "docs" and len(parts) > 1 and not (len(parts) == 2 and rel.endswith(".md")):
            P.add(rel, "layout", "docs holds Markdown files only")
        elif parts[0] == "tools" and (len(parts) != 2 or not rel.endswith(".py")):
            P.add(rel, "layout", "tools holds Python files only")
        elif parts[0] == ".github" and not (len(parts) == 3 and parts[1] == "workflows" and rel.endswith(".yml")):
            P.add(rel, "layout", ".github holds workflow files only")
        elif parts[0] == "agents":
            if len(parts) != 3 or parts[2] != "AGENT.md":
                P.add(rel, "layout", "a starter agent's folder holds AGENT.md and nothing else")
            elif not valid_slug(parts[1]):
                P.add(rel, "layout", "%r isn't a slug" % parts[1])
        elif parts[0] == "skills":
            check_skill_path(rel, parts, P)
        elif parts[0] == "shared":
            check_shared_path(rel, parts, P)


def valid_slug(slug):
    return bool(rules.SLUG.match(slug)) and len(slug) <= rules.SLUG_MAX


def check_skill_path(rel, parts, P):
    if len(parts) < 3:
        P.add(rel, "layout", "a skill is a folder holding SKILL.md")
        return
    if not valid_slug(parts[1]):
        P.add(rel, "layout", "%r isn't a slug (1 to %d characters, lower case, digits, single hyphens)" % (parts[1], rules.SLUG_MAX))
    inside = parts[2:]
    if len(inside) == 1:
        if inside[0] != "SKILL.md":
            P.add(rel, "layout", "only SKILL.md, scripts/, assets/, references/ and examples/ go in a skill's folder")
        return
    folder = inside[0]
    if folder not in rules.SKILL_FOLDERS:
        P.add(rel, "layout", "%r isn't a folder a skill may have" % folder)
    elif not allowed_in_folder(folder, "/".join(inside[1:])):
        P.add(rel, "layout", "a file of this type doesn't belong in %s/" % folder)


def check_shared_path(rel, parts, P):
    inside = parts[1:]
    if len(inside) == 1:
        if inside[0] not in ("rules.md", "agent-intro.md"):
            P.add(rel, "layout", "shared/ holds rules.md, agent-intro.md, references/, scripts/ and assets/")
        return
    if inside[0] not in ("references", "scripts", "assets"):
        P.add(rel, "layout", "%r isn't a shared folder" % inside[0])
    elif not allowed_in_folder(inside[0], "/".join(inside[1:])):
        P.add(rel, "layout", "a file of this type doesn't belong in shared/%s/" % inside[0])


# ---------------------------------------------------------------------------------------------
# Skills and agents: reading them
# ---------------------------------------------------------------------------------------------

class Doc:
    """A SKILL.md or AGENT.md taken apart: its frontmatter lines, the title, the introduction
    and its `## ` sections, where a `## ` line inside a code fence isn't a heading."""

    def __init__(self, text, body_start):
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()  # the final new line
        self.head = lines[:body_start]  # the frontmatter, its closing line and the blank line
        self.title = lines[body_start] if body_start < len(lines) else ""
        rest = lines[body_start + 1:]
        self.intro, self.sections = [], []  # sections: [name, [lines]]
        fenced = False
        current = self.intro
        for line in rest:
            if line.startswith("```"):
                fenced = not fenced
            if not fenced and line.startswith("## "):
                self.sections.append([line[3:], []])
                current = self.sections[-1][1]
            else:
                current.append(line)

    @staticmethod
    def trimmed(lines):
        lines = list(lines)
        while lines and lines[0] == "":
            lines.pop(0)
        while lines and lines[-1] == "":
            lines.pop()
        return lines

    def names(self):
        return [name for name, _ in self.sections]

    def section(self, name):
        for found, lines in self.sections:
            if found == name:
                return self.trimmed(lines)
        return None

    def render(self):
        """The file's text, with one blank line after a heading and between blocks."""
        out = list(self.head) + [self.title]
        intro = self.trimmed(self.intro)
        if intro:
            out += [""] + intro
        for name, lines in self.sections:
            out += ["", "## " + name]
            body = self.trimmed(lines)
            if body:
                out += [""] + body
        return "\n".join(out) + "\n"


def script_files(tree, base):
    """The command scripts and modules in a folder like `skills/x/scripts` (names)."""
    return sorted(p for p in (q[len(base) + 1:] for q in tree.files() if q.startswith(base + "/"))
                  if "/" not in p and p.endswith(".py"))


def is_module(name):
    return name.startswith(rules.MODULE_PREFIX)


def skill_slugs(tree):
    found = set()
    for rel in tree.files():
        parts = rel.split("/")
        if parts[0] == "skills" and len(parts) >= 3:
            found.add(parts[1])
    return sorted(found)


def agent_slugs(tree):
    return sorted({p.split("/")[1] for p in tree.files() if p.startswith("agents/") and len(p.split("/")) >= 3})


def kit_paths(tree, slug):
    """Every file an agent fetches besides SKILL.md: all but `examples/`, sorted by their bytes."""
    prefix = "skills/%s/" % slug
    found = []
    for rel in tree.files():
        if rel.startswith(prefix):
            inside = rel[len(prefix):]
            if inside == "SKILL.md" or inside.startswith("examples/"):
                continue
            found.append(inside)
    return sorted(found, key=lambda p: p.encode("utf-8"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def get_the_kit(slug, kit):
    """The text of `## Get the kit` (4.4)."""
    folder = "skills/" + slug
    return [
        "This skill's kit is the folder %s of %s (public: no account needed). If its files aren't next to "
        "this file, either:" % (folder, rules.REPO_URL),
        "- run `git clone --depth 1 %s.git` and work in hrizzup-skills/%s; or" % (rules.REPO_URL, folder),
        "- download each file below from %s/%s/<file>, keeping its path." % (rules.RAW_URL, folder),
        "Run every command in this skill from that folder. When this skill's version on Hrizzup changes, "
        "get the kit again.",
        "Files: " + ", ".join("`%s`" % p for p in kit),
        "A real sample made with it, and how: %s/tree/main/%s/examples" % (rules.REPO_URL, folder),
    ]


def shared_text(tree, name):
    """What follows the first `# ` line of shared/rules.md or shared/agent-intro.md, trimmed."""
    text = tree.text("shared/" + name)
    if text is None:
        return None
    lines = text.rstrip("\n").split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return Doc.trimmed(lines)


# ---------------------------------------------------------------------------------------------
# Generating: shared copies, sections, the README's table, catalogue.json (4.4)
# ---------------------------------------------------------------------------------------------

def apply_shared_copies(tree):
    """A skill that holds a file of the same path as one in shared/ gets the shared bytes."""
    for rel in tree.files():
        parts = rel.split("/")
        if parts[0] != "shared" or len(parts) < 3 or parts[1] not in rules.SHARED_COPY_FOLDERS:
            continue
        inside = "/".join(parts[1:])
        data = tree.read(rel)
        for slug in skill_slugs(tree):
            target = "skills/%s/%s" % (slug, inside)
            if tree.exists(target) and tree.read(target) != data:
                tree.put(target, data)


def read_skill(tree, slug, P=None):
    """(fields, Doc, problems) for skills/<slug>/SKILL.md, or (None, None, problems)."""
    rel = "skills/%s/SKILL.md" % slug
    if not tree.exists(rel):
        return None, None, ["missing SKILL.md"]
    text = tree.text(rel)
    if text is None:
        return None, None, ["not UTF-8"]
    fields, body_start, problems = frontmatter.parse(text, frontmatter.SKILL, slug)
    if fields is None:
        return None, None, problems
    return fields, Doc(text, body_start), problems


def read_agent(tree, slug):
    rel = "agents/%s/AGENT.md" % slug
    if not tree.exists(rel):
        return None, None, ["missing AGENT.md"]
    text = tree.text(rel)
    if text is None:
        return None, None, ["not UTF-8"]
    fields, body_start, problems = frontmatter.parse(text, frontmatter.AGENT, slug)
    if fields is None:
        return None, None, problems
    return fields, Doc(text, body_start), problems


def generate_skill_sections(tree, slug):
    """Rewrite one SKILL.md's `## Get the kit` and `## Hrizzup's rules`. Returns problems, or []."""
    fields, doc, problems = read_skill(tree, slug)
    if doc is None:
        return problems
    kit = kit_paths(tree, slug)
    kit_lines = get_the_kit(slug, kit) if kit else None
    rules_lines = shared_text(tree, "rules.md")
    # `## Get the kit` sits just before `## Steps`; `## Hrizzup's rules` is last.
    doc.sections = [s for s in doc.sections if s[0] not in ("Get the kit", "Hrizzup's rules")]
    if kit_lines is not None:
        position = next((i for i, s in enumerate(doc.sections) if s[0] == "Steps"), len(doc.sections))
        doc.sections.insert(position, ["Get the kit", kit_lines])
    if rules_lines is not None:
        doc.sections.append(["Hrizzup's rules", rules_lines])
    tree.put("skills/%s/SKILL.md" % slug, doc.render())
    return []


def starter_agent_skills(fields):
    return fields["hrizzup-skills"].split(" ")


def generate_agent_sections(tree, slug):
    fields, doc, problems = read_agent(tree, slug)
    if doc is None:
        return problems
    intro = shared_text(tree, "agent-intro.md")
    if intro is not None:
        doc.intro = intro
    skills_lines = ["- " + s for s in starter_agent_skills(fields)] if "hrizzup-skills" in fields else []
    doc.sections = [s for s in doc.sections if s[0] != "Skills"]
    doc.sections.append(["Skills", skills_lines])
    tree.put("agents/%s/AGENT.md" % slug, doc.render())
    return []


def content_hash(item):
    """The lower-case hex SHA-256 of the item without `contentHash`, canonicalised as RFC 8785 (11)."""
    bare = {k: v for k, v in item.items() if k != "contentHash"}
    canonical = json.dumps(bare, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(canonical.encode("utf-8"))


def skill_item(tree, slug):
    fields, doc, problems = read_skill(tree, slug)
    if fields is None or problems:
        return None
    text = tree.text("skills/%s/SKILL.md" % slug)
    kit = kit_paths(tree, slug)
    needs = fields["hrizzup-needs"]
    item = {
        "slug": slug,
        "kind": "skill",
        "name": fields["hrizzup-name"],
        "summary": fields["hrizzup-summary"],
        "needs": None if needs == "Nothing" else needs,
        "format": fields.get("hrizzup-format"),
        "path": "skills/" + slug,
        "contentHash": "",
        "body": text[:-1] if text.endswith("\n") else text,
        "meta": {
            "kit": kit,
            "kitSha256": {p: sha256(tree.read("skills/%s/%s" % (slug, p))) for p in kit},
        },
    }
    item["contentHash"] = content_hash(item)
    return item


def agent_item(tree, slug):
    fields, doc, problems = read_agent(tree, slug)
    if fields is None or problems:
        return None
    text = tree.text("agents/%s/AGENT.md" % slug)
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line == "# " + fields["hrizzup-name"])
    body = "\n".join(lines[start:])
    item = {
        "slug": slug,
        "kind": "starter-agent",
        "name": fields["hrizzup-name"],
        "summary": fields["hrizzup-summary"],
        "needs": None,
        "format": None,
        "path": "agents/" + slug,
        "contentHash": "",
        "body": body[:-1] if body.endswith("\n") else body,
        "meta": {"skills": starter_agent_skills(fields)},
    }
    item["contentHash"] = content_hash(item)
    return item


def build_items(tree):
    items = []
    for slug in skill_slugs(tree):
        item = skill_item(tree, slug)
        if item is not None:
            items.append(item)
    for slug in agent_slugs(tree):
        item = agent_item(tree, slug)
        if item is not None:
            items.append(item)
    items.sort(key=lambda i: (rules.KINDS.index(i["kind"]), i["slug"]))
    return items


def catalogue_text(items):
    document = {"version": rules.CATALOGUE_VERSION, "items": items}
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def escape_cell(text):
    return text.replace("|", "\\|")


def readme_table(items):
    rows = ["| Name | Kind | What it does | What it needs | Folder |", "|---|---|---|---|---|"]
    for item in items:
        kind = "Skill" if item["kind"] == "skill" else "Starter agent"
        needs = item["needs"] if item["needs"] else "Nothing"
        rows.append("| %s | %s | %s | %s | [%s](%s) |" % (
            escape_cell(item["name"]), kind, escape_cell(item["summary"]), escape_cell(needs), item["path"], item["path"]))
    return "\n".join(rows)


def apply_readme_table(tree, items):
    text = tree.text("README.md") if tree.exists("README.md") else None
    if text is None or text.count(rules.README_START) != 1 or text.count(rules.README_END) != 1:
        return ["must hold %s and %s once each" % (rules.README_START, rules.README_END)]
    start = text.index(rules.README_START) + len(rules.README_START)
    end = text.index(rules.README_END)
    if end < start:
        return ["the end marker comes before the start marker"]
    tree.put("README.md", text[:start] + "\n" + readme_table(items) + "\n" + text[end:])
    return []


def generate(tree):
    """Make every generated file in memory, in the order of 4.4.

    Returns (problems that stop it, as (path, rule, message), the catalogue's items).
    """
    problems = []
    apply_shared_copies(tree)
    for slug in skill_slugs(tree):
        problems += [("skills/%s/SKILL.md" % slug, "frontmatter", p) for p in generate_skill_sections(tree, slug)]
    for slug in agent_slugs(tree):
        problems += [("agents/%s/AGENT.md" % slug, "frontmatter", p) for p in generate_agent_sections(tree, slug)]
    items = build_items(tree)
    problems += [("README.md", "generated", p) for p in apply_readme_table(tree, items)]
    tree.put("catalogue.json", catalogue_text(items))
    return problems, items


# ---------------------------------------------------------------------------------------------
# The catalogue's own rules (skills-catalogue.md)
# ---------------------------------------------------------------------------------------------

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def one_line_problems(name, value, low, high):
    if not isinstance(value, str):
        return ["%s isn't text" % name]
    found = []
    if not low <= len(value) <= high:
        found.append("%s is %d characters; %d to %d" % (name, len(value), low, high))
    if value != value.strip(" ") or any(not rules.catalogue_char_ok(c) for c in value):
        found.append("%s has a space at an end, or a character catalogue text can't hold" % name)
    return found


def check_catalogue(document, text, P):
    path = "catalogue.json"
    if not isinstance(document, dict) or list(document) != ["version", "items"] or document["version"] != rules.CATALOGUE_VERSION:
        P.add(path, "catalogue", "must be {\"version\": 1, \"items\": [...]}")
        return
    if len(text.encode("utf-8")) > rules.CATALOGUE_MAX_BYTES:
        P.add(path, "catalogue", "over 1 MiB")
    items = document["items"]
    seen = {}
    order = []
    for item in items:
        where = "catalogue.json item %r" % item.get("slug") if isinstance(item, dict) else "catalogue.json item"
        if not isinstance(item, dict) or tuple(item) != rules.ITEM_KEYS:
            P.add(path, "catalogue", "%s: exactly these keys, in this order: %s" % (where, ", ".join(rules.ITEM_KEYS)))
            continue
        slug = item["slug"]
        if not valid_slug(slug):
            P.add(path, "catalogue", "%s: not a slug of 1 to %d characters" % (where, rules.SLUG_MAX))
        if slug in seen:
            P.add(path, "catalogue", "%s: the slug is used twice (it is unique across both kinds)" % where)
        seen[slug] = item
        if item["kind"] not in rules.KINDS:
            P.add(path, "catalogue", "%s: kind %r" % (where, item["kind"]))
            continue
        order.append((rules.KINDS.index(item["kind"]), slug))
        for p in one_line_problems("name", item["name"], 1, rules.NAME_MAX) + \
                one_line_problems("summary", item["summary"], 1, rules.SUMMARY_MAX):
            P.add(path, "catalogue", "%s: %s" % (where, p))
        if item["needs"] is not None:
            for p in one_line_problems("needs", item["needs"], 1, rules.NEEDS_MAX):
                P.add(path, "catalogue", "%s: %s" % (where, p))
        if item["format"] is not None and item["format"] not in rules.FORMATS:
            P.add(path, "catalogue", "%s: format %r isn't one of Hrizzup's eight codes" % (where, item["format"]))
        folder = ("skills/" if item["kind"] == "skill" else "agents/") + slug
        if item["path"] != folder:
            P.add(path, "catalogue", "%s: path must be %s" % (where, folder))
        if not isinstance(item["contentHash"], str) or not HEX64.match(item["contentHash"]):
            P.add(path, "catalogue", "%s: contentHash is 64 lower-case hex characters" % where)
        elif item["contentHash"] != content_hash(item):
            P.add(path, "catalogue", "%s: contentHash isn't the hash of the item" % where)
        body = item["body"]
        if not isinstance(body, str) or not 1 <= len(body) <= rules.BODY_MAX_CHARS:
            P.add(path, "catalogue", "%s: body must be 1 to %d characters" % (where, rules.BODY_MAX_CHARS))
        else:
            if body.count("\n") + 1 > rules.BODY_MAX_LINES:
                P.add(path, "catalogue", "%s: body is over %d lines" % (where, rules.BODY_MAX_LINES))
            if "\r" in body or body.endswith("\n"):
                P.add(path, "catalogue", "%s: body has a CR or a final new line" % where)
            if any(not rules.catalogue_char_ok(c, newline=True) for c in body):
                P.add(path, "catalogue", "%s: body has a character catalogue text can't hold" % where)
            if item["kind"] == "starter-agent" and len(body) > rules.AGENT_BODY_MAX:
                P.add(path, "catalogue", "%s: an agent's body is at most %d characters" % (where, rules.AGENT_BODY_MAX))
        meta = item["meta"]
        if not isinstance(meta, dict):
            P.add(path, "catalogue", "%s: meta isn't an object" % where)
        elif item["kind"] == "skill":
            kit = meta.get("kit")
            sums = meta.get("kitSha256")
            if not isinstance(kit, list) or not isinstance(sums, dict):
                P.add(path, "catalogue", "%s: meta needs kit (a list) and kitSha256 (an object)" % where)
            else:
                if kit != sorted(kit, key=lambda p: p.encode("utf-8")):
                    P.add(path, "catalogue", "%s: meta.kit isn't sorted by bytes" % where)
                if set(sums) != set(kit) or not all(isinstance(v, str) and HEX64.match(v) for v in sums.values()):
                    P.add(path, "catalogue", "%s: kitSha256 must hold a 64-hex digest for exactly the paths in kit" % where)
                if any(p.startswith("examples/") or p == "SKILL.md" for p in kit):
                    P.add(path, "catalogue", "%s: samples and SKILL.md are never in the kit" % where)
    if order != sorted(order):
        P.add(path, "catalogue", "items must be sorted by kind (skill first), then slug")
    for item in items:
        if isinstance(item, dict) and item.get("kind") == "starter-agent" and isinstance(item.get("meta"), dict):
            names = item["meta"].get("skills")
            if not isinstance(names, list) or not 1 <= len(names) <= rules.AGENT_SKILLS_MAX or len(set(names)) != len(names):
                P.add(path, "catalogue", "agent %r: meta.skills is one to %d slugs, no repeats" % (item["slug"], rules.AGENT_SKILLS_MAX))
                continue
            for name in names:
                if name not in seen or seen[name]["kind"] != "skill":
                    P.add(path, "catalogue", "agent %r: meta.skills names %r, which isn't a skill in this file" % (item["slug"], name))


# ---------------------------------------------------------------------------------------------
# A skill's SKILL.md (4.1, 4.3): the parts a person writes
# ---------------------------------------------------------------------------------------------

NAMED_PATH = re.compile(r"(?<![A-Za-z0-9._/-])(?:scripts|assets|references)/[A-Za-z0-9._/-]*[A-Za-z0-9_]")


def sentence_count(lines):
    text = re.sub(r"`[^`]*`", "x", " ".join(lines))
    return len(re.findall(r"[.!?]+(?=\s|$)", text))


def check_skill_doc(tree, slug, P):
    rel = "skills/%s/SKILL.md" % slug
    fields, doc, problems = read_skill(tree, slug)
    for p in problems:
        P.add(rel, "frontmatter", p)
    if doc is None:
        return None
    text = tree.text(rel)
    for p in catalogue_text_problems(text):
        P.add(rel, "text", p)
    body = text[:-1] if text.endswith("\n") else text
    if len(body) > rules.BODY_MAX_CHARS:
        P.add(rel, "body", "%d characters; at most %d" % (len(body), rules.BODY_MAX_CHARS))
    if body.count("\n") + 1 > rules.BODY_MAX_LINES:
        P.add(rel, "body", "%d lines; at most %d" % (body.count("\n") + 1, rules.BODY_MAX_LINES))
    scripts = script_files(tree, "skills/%s/scripts" % slug)
    has_scripts = any(p.startswith("skills/%s/scripts/" % slug) for p in tree.files())
    if has_scripts and "compatibility" not in fields:
        P.add(rel, "frontmatter", "`compatibility` is missing: a skill with scripts/ names its exact technical needs there")
    if not has_scripts and "compatibility" in fields:
        P.add(rel, "frontmatter", "`compatibility` is only for a skill with a scripts/ folder")
    intro = doc.trimmed(doc.intro)
    if not intro:
        P.add(rel, "body", "no introduction (1 to 3 sentences) after the title")
    elif sentence_count(intro) > 3:
        P.add(rel, "body", "the introduction runs to more than 3 sentences")
    names = doc.names()
    kit = kit_paths(tree, slug)
    expected_head = ["When to use", "What you need"] + (["Get the kit"] if kit else []) + ["Steps"]
    tail = ["Post it", "Hrizzup's rules"]
    if names[:len(expected_head)] != expected_head:
        P.add(rel, "body", "the sections must start: " + ", ".join("## " + n for n in expected_head) + "; found: " + ", ".join(names))
    elif names[-2:] != tail:
        P.add(rel, "body", "the last two sections must be ## Post it and ## Hrizzup's rules")
    else:
        for name in names[len(expected_head):-2]:
            if name in rules.SKILL_SECTIONS:
                P.add(rel, "body", "## %s is out of its place" % name)
    for name in set(names):
        if names.count(name) > 1:
            P.add(rel, "body", "## %s appears twice" % name)
    steps = doc.section("Steps")
    if steps is not None and not any(re.match(r"^1\. ", line) for line in steps):
        P.add(rel, "body", "## Steps must be a numbered list starting at 1.")
    need = doc.section("What you need")
    if need is not None:
        need_text = "\n".join(need)
        if not need_text.strip():
            P.add(rel, "body", "## What you need is empty")
        for name in scripts:
            if is_module(name):
                continue
            requirements = "scripts/%s.requirements.txt" % name[:-3]
            if tree.exists("skills/%s/%s" % (slug, requirements)) and ("--require-hashes -r " + requirements) not in need_text:
                P.add(rel, "body", "## What you need must give the no-uv path for %s: `... pip install --require-hashes -r %s`" % (name, requirements))
        if any(not is_module(n) for n in scripts) and "uv" not in need_text:
            P.add(rel, "body", "## What you need must say to use Python 3.12 with uv (`pip install uv`)")
    post = doc.section("Post it")
    if post is not None and fields.get("hrizzup-format") and ("`%s`" % fields["hrizzup-format"]) not in "\n".join(post):
        P.add(rel, "body", "## Post it must name the format code `%s`" % fields["hrizzup-format"])
    for found in sorted(set(NAMED_PATH.findall(body))):
        if not (tree.exists("skills/%s/%s" % (slug, found)) or any(p.startswith("skills/%s/%s/" % (slug, found)) for p in tree.files())):
            P.add(rel, "body", "names %s, which isn't in the skill's folder" % found)
    return fields


def agent_style(lines):
    """The first fenced `json` block in a section's lines, parsed; or None."""
    inside, block = False, []
    for line in lines:
        if not inside and line.strip() == "```json":
            inside = True
        elif inside and line.strip() == "```":
            try:
                return json.loads("\n".join(block))
            except ValueError:
                return None
        elif inside:
            block.append(line)
    return None


def check_agent_doc(tree, slug, skills, P):
    rel = "agents/%s/AGENT.md" % slug
    fields, doc, problems = read_agent(tree, slug)
    for p in problems:
        P.add(rel, "frontmatter", p)
    if doc is None:
        return
    text = tree.text(rel)
    for p in catalogue_text_problems(text):
        P.add(rel, "text", p)
    body = "\n".join(text.split("\n")[len(doc.head):]).rstrip("\n")
    if len(body) > rules.AGENT_BODY_MAX:
        P.add(rel, "body", "%d characters; an agent's body is at most %d" % (len(body), rules.AGENT_BODY_MAX))
    if doc.names() != list(rules.AGENT_SECTIONS):
        P.add(rel, "body", "the sections must be, in order: " + ", ".join("## " + n for n in rules.AGENT_SECTIONS))
    for name, lines in doc.sections:
        section = "\n".join(doc.trimmed(lines))
        if not section:
            if name != "Skills":
                P.add(rel, "body", "## %s is empty" % name)
        elif len(section) > rules.AGENT_SECTION_MAX:
            P.add(rel, "body", "## %s is %d characters; at most %d" % (name, len(section), rules.AGENT_SECTION_MAX))
    style_lines = doc.section("Style")
    if style_lines is not None:
        style = agent_style(style_lines)
        if not isinstance(style, dict):
            P.add(rel, "body", "## Style must hold one fenced `json` block with the agent's style")
        else:
            if not set(rules.STYLE_DEFAULT) <= set(style):
                P.add(rel, "body", "## Style must hold every key of the default style (8.1)")
            for key in ("ink", "paper", "accent"):
                if key in style and not (isinstance(style[key], str) and re.match(r"^#[0-9A-Fa-f]{6}$", style[key])):
                    P.add(rel, "body", "## Style: %s must be a #RRGGBB colour" % key)
    if "hrizzup-skills" in fields:
        for name in starter_agent_skills(fields):
            if name not in skills:
                P.add(rel, "frontmatter", "`hrizzup-skills` names %r, which isn't a skill in this repository" % name)


# ---------------------------------------------------------------------------------------------
# Scripts (5)
# ---------------------------------------------------------------------------------------------

HEADER = re.compile(r"(?m)^# /// script$\s(?P<content>(?:^#(?:| .*)$\s)+)^# ///$")
REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+!-]*)$")


def read_header(source):
    """The PEP 723 header's TOML, as a dict; None if there is none."""
    found = HEADER.search(source)
    if not found:
        return None
    lines = []
    for line in found.group("content").splitlines():
        lines.append(line[2:] if line.startswith("# ") else line[1:])
    return tomllib.loads("\n".join(lines))


def script_header_problems(name, header):
    found = []
    deps = header.get("dependencies", None)
    python = header.get("requires-python")
    uv = header.get("tool", {}).get("uv", {}) if isinstance(header.get("tool"), dict) else {}
    if not isinstance(deps, list):
        return ["the header needs `dependencies = [...]` (empty for a standard-library-only script)"]
    if not deps:
        if python != rules.STDLIB_REQUIRES_PYTHON:
            found.append("a standard-library-only script says `requires-python = \"%s\"`" % rules.STDLIB_REQUIRES_PYTHON)
        return found
    if python != rules.REQUIRES_PYTHON:
        found.append("`requires-python` must be \"%s\"" % rules.REQUIRES_PYTHON)
    if uv.get("exclude-newer") != rules.EXCLUDE_NEWER:
        found.append("`[tool.uv] exclude-newer` must be \"%s\", the repository's one date" % rules.EXCLUDE_NEWER)
    seen = set()
    for dep in deps:
        match = REQUIREMENT.match(dep) if isinstance(dep, str) else None
        if not match:
            found.append("dependency %r must be pinned exactly, as `name==version`" % (dep,))
            continue
        package, version = norm_name(match.group(1)), match.group(2)
        if package in seen:
            found.append("%s is listed twice" % package)
        seen.add(package)
        if package not in rules.PINS:
            found.append("%s isn't a package the repository pins (tools/rules.py PINS, docs/design.md 5)" % package)
        elif rules.PINS[package] != version:
            found.append("%s must be pinned to %s, the repository's one pin" % (package, rules.PINS[package]))
    return found


def top_level_imports(tree_ast):
    """Module names imported at the top of a file (inside `if` and `try` too), not inside functions."""
    found = []

    def walk(statements):
        for node in statements:
            if isinstance(node, ast.Import):
                found.extend((alias.name.split(".")[0], node.lineno) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.append((("." * node.level) + (node.module or "").split(".")[0], node.lineno))
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(node, field, []))
                for handler in getattr(node, "handlers", []):
                    walk(handler.body)

    walk(tree_ast.body)
    return found


def all_imports(tree_ast):
    found = []
    for node in ast.walk(tree_ast):
        if isinstance(node, ast.Import):
            found.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module.split(".")[0])
    return found


def run_help(path):
    """(exit code, stdout) of `python <script> --help`, run in its own folder with nothing added."""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "LC_ALL": "C.UTF-8"}
    try:
        done = subprocess.run(
            [sys.executable, "-B", os.path.basename(path), "--help"], cwd=os.path.dirname(path),
            capture_output=True, text=True, timeout=rules.HELP_TIMEOUT_SECONDS, env=env,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return 1, "could not run: %s" % error
    return done.returncode, done.stdout + done.stderr if done.returncode else done.stdout


def check_script(tree, rel, P, run=True):
    """Every rule for one .py file in a scripts/ folder. Returns its header's dependencies, or None."""
    name = rel.rsplit("/", 1)[-1]
    source = tree.text(rel)
    if source is None:
        return None
    try:
        parsed = ast.parse(source, rel)
    except SyntaxError as error:
        P.add(rel, "script", "doesn't parse: %s" % error)
        return None
    module = is_module(name)
    imports = all_imports(parsed)
    for package in rules.GPL_MODULES:
        if package in imports and name not in rules.GPL_ALLOWED:
            P.add(rel, "script", "imports %s: only voice.py may (it is GPL)" % package)
    for package in rules.FFMPEG_MODULES:
        if package in imports and name not in rules.FFMPEG_ALLOWED:
            P.add(rel, "script", "imports %s: FFmpeg runs only through hrizzup_media's builders" % package)
    for package in rules.NETWORK_MODULES:
        if package in imports and name not in rules.NETWORK_ALLOWED:
            P.add(rel, "script", "imports %s: only check_links.py, voice.py and captions.py use the network" % package)
    stdlib = sys.stdlib_module_names
    top_ok = ("hrizzup_media",) + (rules.DRAW_TOP_IMPORTS if name == "hrizzup_draw.py" else ())
    for package, line in top_level_imports(parsed):
        if package.startswith("."):
            P.add(rel, "script", "line %d: a relative import; scripts import siblings by name" % line)
        elif package not in stdlib and package not in top_ok:
            P.add(rel, "script", "line %d: imports %s at the top; packages and hrizzup_draw go inside functions" % (line, package))
    if module:
        if HEADER.search(source):
            P.add(rel, "script", "a module has no script header")
        return None
    header = None
    try:
        header = read_header(source)
    except tomllib.TOMLDecodeError as error:
        P.add(rel, "script", "the script header isn't valid TOML: %s" % error)
    if header is None:
        P.add(rel, "script", "no `# /// script` header")
        return None
    for problem in script_header_problems(name, header):
        P.add(rel, "script", problem)
    for node in ast.walk(parsed):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "input":
            P.add(rel, "script", "line %d: input() asks a question; a command takes flags only" % node.lineno)
    if run:
        code, output = run_help(str(tree.root / rel))
        if code != 0 or "usage:" not in output:
            P.add(rel, "script", "`python3 %s --help` must exit 0 and print 'usage:' with nothing installed (exit %d)" % (name, code))
        else:
            tail = "\n".join(output.strip().split("\n")[-rules.HELP_TAIL_LINES:]).lower()
            if "example" not in tail or name.lower() not in tail:
                P.add(rel, "script", "--help must end with an example that names %s" % name)
            if name in rules.OFFLINE_SCRIPTS and "--offline" not in output:
                P.add(rel, "script", "must take --offline, which refuses to download")
    return header.get("dependencies", [])


def script_folders(tree):
    folders = set()
    for rel in tree.files():
        parts = rel.split("/")
        if len(parts) == 4 and parts[0] == "skills" and parts[2] == "scripts":
            folders.add("/".join(parts[:3]))
        elif len(parts) == 3 and parts[0] == "shared" and parts[1] == "scripts":
            folders.add("shared/scripts")
    return sorted(folders)


def check_scripts(tree, P, run=True):
    """The scripts' rules, and each script that has packages with its lock and requirements file.

    Returns {script path: its dependencies} for the commands.
    """
    found = {}
    for folder in script_folders(tree):
        names = sorted(p[len(folder) + 1:] for p in tree.files() if p.startswith(folder + "/") and "/" not in p[len(folder) + 1:])
        for name in names:
            rel = folder + "/" + name
            if name.endswith(".py"):
                deps = check_script(tree, rel, P, run=run)
                if deps is not None:
                    found[rel] = deps
            elif name.endswith(".py.lock"):
                if name[:-5] not in names:
                    P.add(rel, "locks", "a lock with no script beside it")
            elif name.endswith(".requirements.txt"):
                if name[:-len(".requirements.txt")] + ".py" not in names:
                    P.add(rel, "locks", "a requirements file with no script beside it")
    return found


# ---------------------------------------------------------------------------------------------
# Locks and NOTICES.md (5, 7.2.5)
# ---------------------------------------------------------------------------------------------

LOCK_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")
HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def parse_requirements(text):
    """{normalised name: (version, {hashes})} from a pip requirements file uv exported."""
    found, current = {}, None
    for line in text.split("\n"):
        pin = LOCK_PIN.match(line)
        if pin and not line.startswith((" ", "#")):
            current = norm_name(pin.group(1))
            found[current] = (pin.group(2), set())
        for digest in HASH.findall(line):
            if current is not None:
                found[current][1].add(digest)
    return found


def lock_packages(document):
    """{normalised name: (version, {hashes})} from a parsed uv.lock-format lock."""
    found = {}
    for package in document.get("package", []):
        hashes = set()
        entries = list(package.get("wheels", []))
        if isinstance(package.get("sdist"), dict):
            entries.append(package["sdist"])
        for entry in entries:
            value = entry.get("hash", "")
            if value.startswith("sha256:"):
                hashes.add(value[7:])
        found[norm_name(package["name"])] = (package.get("version", ""), hashes)
    return found


def check_locks(tree, scripts, P):
    """Each script with packages has a lock and a requirements file that match its header.

    Returns {normalised package: set of versions} over all the locks.
    """
    resolved = {}
    for rel, deps in sorted(scripts.items()):
        lock, requirements = rel + ".lock", rel[:-3] + ".requirements.txt"
        if not deps:
            for orphan in (lock, requirements):
                if tree.exists(orphan):
                    P.add(orphan, "locks", "%s has no packages, so it needs no lock" % rel.rsplit("/", 1)[-1])
            continue
        missing = [p for p in (lock, requirements) if not tree.exists(p)]
        for p in missing:
            P.add(p, "locks", "missing: a script with packages carries its lock and its hashed requirements file (docs/design.md, 5)")
        if missing:
            continue
        try:
            document = tomllib.loads(tree.text(lock) or "")
        except tomllib.TOMLDecodeError as error:
            P.add(lock, "locks", "isn't valid TOML: %s" % error)
            continue
        want = {(norm_name(REQUIREMENT.match(d).group(1)), "==" + REQUIREMENT.match(d).group(2))
                for d in deps if isinstance(d, str) and REQUIREMENT.match(d)}
        manifest = {(norm_name(r.get("name", "")), r.get("specifier", "")) for r in document.get("manifest", {}).get("requirements", [])}
        if manifest != want:
            P.add(lock, "locks", "its manifest doesn't match the script's header: lock again (uv lock --script)")
        if document.get("options", {}).get("exclude-newer") != rules.EXCLUDE_NEWER:
            P.add(lock, "locks", "its exclude-newer isn't %s" % rules.EXCLUDE_NEWER)
        if str(document.get("requires-python", "")).replace(" ", "") != rules.REQUIRES_PYTHON:
            P.add(lock, "locks", "its requires-python isn't %s" % rules.REQUIRES_PYTHON)
        locked = lock_packages(document)
        for package, (version, _hashes) in locked.items():
            if not version:
                P.add(lock, "locks", "%s has no version" % package)
            resolved.setdefault(package, set()).add(version)
            if package in rules.PINS and version != rules.PINS[package]:
                P.add(lock, "locks", "%s is locked at %s, not the repository's pin %s" % (package, version, rules.PINS[package]))
        exported = parse_requirements(tree.text(requirements) or "")
        if set(exported) != set(locked):
            P.add(requirements, "locks", "holds a different set of packages from its lock (%s): export again" %
                  ", ".join(sorted(set(exported) ^ set(locked))[:5]))
        for package, (version, hashes) in exported.items():
            if package in locked:
                if version != locked[package][0]:
                    P.add(requirements, "locks", "%s is %s here and %s in the lock" % (package, version, locked[package][0]))
                if not hashes or not hashes <= locked[package][1]:
                    P.add(requirements, "locks", "%s needs hashes, all of them from the lock" % package)
    for package, versions in sorted(resolved.items()):
        if len(versions) > 1:
            P.add("shared/scripts", "locks", "%s is locked at %s: one version across the repository" % (package, " and ".join(sorted(versions))))
    return resolved


def parse_notices(text):
    """(header cells, [row cells]) of the first table in NOTICES.md."""
    header, rows, inside = None, [], False
    for line in text.split("\n"):
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if header is None:
                header = cells
            elif not all(re.match(r"^:?-+:?$", c) for c in cells):
                rows.append(cells)
            inside = True
        elif inside:
            break
    return header, rows


def check_notices(tree, resolved, P):
    text = tree.text("NOTICES.md") if tree.exists("NOTICES.md") else None
    if text is None:
        return
    header, rows = parse_notices(text)
    if header != list(rules.NOTICES_COLUMNS):
        P.add("NOTICES.md", "notices", "the table's columns must be: " + " | ".join(rules.NOTICES_COLUMNS))
        return
    index = {name: i for i, name in enumerate(header)}
    good = []
    for cells in rows:
        if len(cells) != len(header):
            P.add("NOTICES.md", "notices", "a row with %d cells, not %d: %s" % (len(cells), len(header), cells[0] if cells else ""))
            continue
        good.append(cells)
        licence = cells[index["Licence"]]
        if re.search(r"(?<![Ll])GPL", licence) and rules.BUNDLED_WORD in cells[index["How it's used"]].lower():
            P.add("NOTICES.md", "notices", "%s is GPL and its row says it is bundled: say what the creator's setup installs" % cells[0])
    names = [(c[index["Name"]], c[index["Version"]], c[index["Licence"]]) for c in good]

    def has_row(package, version):
        return any(norm_name(n) == package and v == version and lic for n, v, lic in names)

    def has_words(words):
        return any(all(w in n.lower() for w in words.split()) and lic for n, _v, lic in names)

    for package, versions in sorted(resolved.items()):
        for version in sorted(versions):
            if not has_row(package, version):
                P.add("NOTICES.md", "notices", "no row, with a licence, for %s %s" % (package, version))
        for words in rules.NATIVE_NOTICES.get(package, ()):
            if not has_words(words):
                P.add("NOTICES.md", "notices", "no row, with a licence, for \"%s\" (shipped by %s)" % (words, package))
    folders = {}
    for rel in tree.files():
        if rel.endswith(".ttf"):
            folders.setdefault(rel.rsplit("/", 1)[0], []).append(rel)
    for folder in sorted(folders):
        family = folder.rsplit("/", 1)[-1]
        if not tree.exists(folder + "/" + rules.LICENCE_FILE):
            P.add(folder, "notices", "a font family folder must hold its %s" % rules.LICENCE_FILE)
        elif "OPEN FONT LICENSE" not in (tree.text(folder + "/" + rules.LICENCE_FILE) or "").upper():
            P.add(folder + "/" + rules.LICENCE_FILE, "notices", "isn't the SIL Open Font License text")
        key = re.sub(r"[^a-z0-9]", "", family.lower())
        if not any(key in re.sub(r"[^a-z0-9]", "", n.lower()) and lic for n, _v, lic in names):
            P.add("NOTICES.md", "notices", "no row, with a licence, for the font family %s" % family)


# ---------------------------------------------------------------------------------------------
# Examples (6) and media (7.2.4)
# ---------------------------------------------------------------------------------------------



def check_post(tree, slug, fields, P):
    rel = "skills/%s/examples/post.json" % slug
    text = tree.text(rel)
    try:
        post = json.loads(text)
    except (TypeError, ValueError) as error:
        P.add(rel, "examples", "isn't valid JSON: %s" % error)
        return
    if not isinstance(post, dict):
        P.add(rel, "examples", "must be a JSON object")
        return
    if "requestId" in post:
        P.add(rel, "examples", "is the post without `requestId`")
    allowed = {"storyId", "kind", "format", "body", "sources", "media"}
    for key in sorted(set(post) - allowed):
        P.add(rel, "examples", "unknown key %r" % key)
    if post.get("storyId") != rules.STORY_ID:
        P.add(rel, "examples", "storyId must be the example story's, %s" % rules.STORY_ID)
    kind = post.get("kind")
    if kind not in rules.POST_KINDS:
        P.add(rel, "examples", "kind is one of %s" % ", ".join(rules.POST_KINDS))
        return
    want_format = fields.get("hrizzup-format")
    if post.get("format") != want_format:
        P.add(rel, "examples", "format must be %r, the skill's" % want_format)
    limit = rules.BODY_MAX_POST if kind == "text" else rules.BODY_MAX_CAPTION
    for p in rules.plain_text_problems("body", post.get("body"), limit):
        P.add(rel, "examples", p)
    sources = post.get("sources", [])
    if not isinstance(sources, list) or len(sources) > rules.POST_SOURCES_MAX:
        P.add(rel, "examples", "sources: a list of at most %d web addresses" % rules.POST_SOURCES_MAX)
    else:
        for source in sources:
            for problem in rules.web_address_problems(source):
                P.add(rel, "examples", "sources: %r %s" % (source if isinstance(source, str) else str(source), problem))
    spec = post.get("media")
    if kind == "text":
        if spec is not None:
            P.add(rel, "examples", "a text post has no media")
        return
    if not isinstance(spec, dict):
        P.add(rel, "examples", "a %s post needs media" % kind)
        return
    folder = "skills/%s/examples/" % slug
    pictures = []  # (file, size rule label, allowed sizes)
    if kind == "image":
        sizes = rules.FORMAT_IMAGE_SIZES.get(want_format)
        pictures.append((spec.get("file"), sizes))
        keys = {"file", "description"}
        for p in rules.plain_text_problems("media.description", spec.get("description"), rules.POST_DESCRIPTION_MAX):
            P.add(rel, "examples", p)
    else:
        keys = {"file", "transcript", "still"}
        for p in rules.long_text_problems("media.transcript", spec.get("transcript"), rules.POST_TRANSCRIPT_MAX):
            P.add(rel, "examples", p)
        still = spec.get("still")
        if not isinstance(still, dict):
            P.add(rel, "examples", "media.still needs a file and a description")
        else:
            pictures.append((still.get("file"), (rules.STILL_SIZES[kind],)))
            for p in rules.plain_text_problems("media.still.description", still.get("description"), rules.POST_DESCRIPTION_MAX):
                P.add(rel, "examples", p)
        main = spec.get("file")
        wanted = ".mp4" if kind == "video" else ".m4a"
        if not isinstance(main, str) or not tree.exists(folder + main):
            P.add(rel, "examples", "media.file %r isn't in examples/" % (main,))
        elif not main.endswith(wanted):
            P.add(rel, "examples", "a %s post's media.file ends %s" % (kind, wanted))
    if set(spec) - keys:
        P.add(rel, "examples", "media has unknown keys %s" % sorted(set(spec) - keys))
    for file, sizes in pictures:
        if not isinstance(file, str) or not tree.exists(folder + file):
            P.add(rel, "examples", "%r isn't in examples/" % file)
            continue
        if sizes:
            try:
                info = media.inspect(str(tree.root / (folder + file)))
            except (media.MediaError, OSError):
                continue  # the media check reports it
            if (info.width, info.height) not in sizes:
                P.add(rel, "examples", "%s is %sx%s; Hrizzup wants %s" % (file, info.width, info.height, " or ".join("%dx%d" % s for s in sizes)))


def check_examples(tree, slug, fields, P):
    folder = "skills/%s/examples/" % slug
    readme = folder + "README.md"
    if not tree.exists(readme):
        P.add(readme, "examples", "missing: every skill's examples/ proves it, and its README.md says how")
    else:
        text = tree.text(readme) or ""
        if text.split("\n", 1)[0] != rules.EXAMPLE_FIRST_LINE:
            P.add(readme, "examples", "the first line must be: %s" % rules.EXAMPLE_FIRST_LINE)
        if rules.EXAMPLE_MACHINE not in text:
            P.add(readme, "examples", "must name the machine: \"%s\"" % rules.EXAMPLE_MACHINE)
        for name in tree.folder(folder):
            if name != "README.md" and name not in text:
                P.add(readme, "examples", "doesn't name %s" % name)
        for script in script_files(tree, "skills/%s/scripts" % slug):
            if not is_module(script) and script not in text:
                P.add(readme, "examples", "doesn't show the command that runs %s" % script)
    if not tree.exists(folder + "post.json"):
        P.add(folder + "post.json", "examples", "missing: the post the sample would make")
    else:
        check_post(tree, slug, fields, P)


def check_media(tree, P):
    for rel in tree.files():
        ext = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else ""
        if ext not in (".png", ".jpg", ".webp", ".mp4", ".m4a", ".ttf"):
            continue
        if rel in tree.overrides:
            continue
        full = str(tree.root / rel)
        if ext == ".ttf":
            with open(full, "rb") as f:
                head = f.read(4)
            if head not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                P.add(rel, "media", "isn't a TrueType font file")
            continue
        try:
            info = media.inspect(full)
        except media.MediaError as error:
            P.add(rel, "media", str(error))
            continue
        except OSError as error:
            P.add(rel, "media", "can't be read: %s" % error)
            continue
        role = "image" if ext in rules.IMAGE_EXTENSIONS else ("video" if ext == ".mp4" else "audio")
        if "/examples/" in rel or role == "image":
            for problem in media.problems(info, role):
                P.add(rel, "media", problem)


def box_problems(name, box):
    if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)):
        return ["%s must be a box [x0, y0, x1, y1] of four numbers" % name]
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return ["%s must lie inside the canvas, as fractions: 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1" % name]
    return []


def template_problems(stem, template):
    """Why a template (design 8.1) is wrong. Templates have no colours of their own."""
    if not isinstance(template, dict):
        return ["a template is a JSON object"]
    found = []
    keys = ("id", "sizes", "background", "picture", "texts", "signature")
    if set(template) != set(keys):
        found.append("a template has exactly these keys: %s" % ", ".join(keys))
        return found
    if template["id"] != stem or not valid_slug(str(template["id"])):
        found.append("id must be the file's name without .json (%r), as a slug" % stem)
    sizes = template["sizes"]
    if not isinstance(sizes, list) or not sizes or not all(
            isinstance(s, list) and len(s) == 2 and all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= media.IMAGE_MAX_SIDE for v in s)
            for s in sizes):
        found.append("sizes is a list of [width, height] pairs, each side 1 to %d" % media.IMAGE_MAX_SIDE)
    if template["background"] not in ("paper", "accent"):
        found.append("background is paper or accent")
    picture = template["picture"]
    if picture is not None:
        if not isinstance(picture, dict) or set(picture) != {"box", "required"} or not isinstance(picture.get("required"), bool):
            found.append("picture is null or {\"box\": [...], \"required\": true or false}")
        else:
            found += box_problems("picture.box", picture["box"])
    slots = set()
    texts = template["texts"]
    if not isinstance(texts, list):
        found.append("texts is a list")
        texts = []
    for number, text in enumerate(texts, start=1):
        label = "texts[%d]" % number
        want = {"slot", "box", "font", "max", "min", "lines", "align", "on", "case"}
        if not isinstance(text, dict) or set(text) != want:
            found.append("%s has exactly these keys: %s" % (label, ", ".join(sorted(want))))
            continue
        if not (isinstance(text["slot"], str) and re.match(r"^[a-z][a-z0-9_-]*$", text["slot"])) or text["slot"] in slots:
            found.append("%s: slot is a unique lower-case name" % label)
        slots.add(text["slot"])
        found += ["%s: %s" % (label, p) for p in box_problems("box", text["box"])]
        if text["font"] not in ("display", "text", "text-bold"):
            found.append("%s: font is display, text or text-bold" % label)
        numbers = [text["max"], text["min"], text["lines"]]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in numbers) or not 1 <= text["min"] <= text["max"] <= 400 or not 1 <= text["lines"] <= 10:
            found.append("%s: 1 <= min <= max <= 400 (whole numbers) and 1 <= lines <= 10" % label)
        if text["align"] not in ("left", "center", "right"):
            found.append("%s: align is left, center or right" % label)
        if text["on"] not in ("paper", "accent", "picture"):
            found.append("%s: on is paper, accent or picture" % label)
        elif text["on"] == "picture" and picture is None:
            found.append("%s: text on a picture, but the template has no picture" % label)
        if text["case"] not in ("as-is", "upper"):
            found.append("%s: case is as-is or upper" % label)
    signature = template["signature"]
    if signature is not None:
        if not isinstance(signature, dict) or set(signature) != {"box", "align"} or signature.get("align") not in ("left", "center", "right"):
            found.append("signature is null or {\"box\": [...], \"align\": left, center or right}")
        else:
            found += box_problems("signature.box", signature["box"])
    if re.search(r"#[0-9A-Fa-f]{3,8}\b|colou?r", json.dumps(template)):
        found.append("a template has no colours of its own (the agent's style gives them)")
    return found


def check_templates(tree, P):
    for rel in tree.files():
        parts = rel.split("/")
        if rel.endswith(".json") and len(parts) >= 3 and parts[-2] == "templates" and "assets" in parts:
            try:
                template = json.loads(tree.text(rel) or "")
            except ValueError as error:
                P.add(rel, "template", "isn't valid JSON: %s" % error)
                continue
            for problem in template_problems(parts[-1][:-5], template):
                P.add(rel, "template", problem)


def check_kit_sizes(tree, P):
    for slug in skill_slugs(tree):
        total = sum(tree.size("skills/%s/%s" % (slug, p)) for p in kit_paths(tree, slug))
        if total > rules.KIT_MAX_BYTES:
            P.add("skills/" + slug, "kit", "the kit is %d bytes, over %d (3 MiB, samples not counted)" % (total, rules.KIT_MAX_BYTES))


# ---------------------------------------------------------------------------------------------
# Workflows (7.2.7), ported from hrizzup's .github/scripts/test_public_repo.py
# ---------------------------------------------------------------------------------------------

def without_comments(text):
    kept = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        kept.append(re.sub(r"\s+#\s.*$", "", line))
    return "\n".join(kept) + "\n"


def triggers(text):
    text = without_comments(text)
    inline = re.search(r"^on:[ \t]*(\S.*)$", text, re.M)
    if inline:
        return set(re.findall(r"[a-z_]+", inline.group(1)))
    block = re.search(r"^on:[ \t]*\n((?:[ \t]+\S.*\n|[ \t]*\n)*)", text, re.M)
    if not block:
        return set()
    indents = [len(m.group(1)) for m in re.finditer(r"^([ \t]+)\S", block.group(1), re.M)]
    first = min(indents) if indents else 2
    return set(re.findall(r"^[ \t]{%d}([a-z_]+):" % first, block.group(1), re.M))


def workflow_actions(text):
    return re.findall(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s'\"#]+)", without_comments(text), re.M)


def workflow_scripts(text):
    lines, found = text.splitlines(), []
    for i, line in enumerate(lines):
        match = re.match(r"^(\s*)(-\s+)?run:\s*(.*)$", line)
        if not match:
            continue
        indent = len(match.group(1)) + len(match.group(2) or "")
        body = [match.group(3)]
        if re.fullmatch(r"[|>][+-]?", match.group(3).strip()):
            for following in lines[i + 1:]:
                if following.strip() and len(following) - len(following.lstrip()) <= indent:
                    break
                body.append(following)
        found.append((i + 1, "\n".join(body)))
    return found


YAML_ESCAPE = re.compile(r"\\(?:x([0-9A-Fa-f]{2})|u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8}))")


def unescape(match):
    """One YAML escape (`\\x5f`) as the character it writes; an impossible one is left as it is."""
    try:
        return chr(int(match.group(1) or match.group(2) or match.group(3), 16))
    except (ValueError, OverflowError):
        return match.group(0)


def check_workflow(rel, text, P):
    found = triggers(text)
    if not found:
        P.add(rel, "workflow", "no trigger found; the reader misses its `on:`")
    bad = found & set(rules.FORBIDDEN_TRIGGERS)
    if bad:
        P.add(rel, "workflow", "runs on %s, which runs with the repository's keys on an outsider's pull request" % sorted(bad))
    # Fail closed, whatever the YAML form (quoted keys, flow lists and maps, escapes, a comment mark inside a
    # string): the words themselves may not appear anywhere but in a whole-line comment.
    live = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    decoded = YAML_ESCAPE.sub(unescape, live)
    for word in rules.FORBIDDEN_TRIGGERS:
        if word in live or word in decoded:
            P.add(rel, "workflow", "%s appears outside a comment: that trigger runs with the repository's keys on an "
                  "outsider's pull request, and no spelling of it is allowed" % word)
    for action in workflow_actions(text):
        if not action.startswith("./") and not rules.PINNED_ACTION.match(action):
            P.add(rel, "workflow", "pin %s to a full commit SHA" % action)
    if not re.search(r"^permissions:", text, re.M):
        P.add(rel, "workflow", "no top-level `permissions:`")
    if "write-all" in without_comments(text):
        P.add(rel, "workflow", "`write-all` rights")
    for line, script in workflow_scripts(text):
        for expression in re.findall(r"\$\{\{(.*?)\}\}", script, re.S):
            if not rules.SAFE_IN_SCRIPTS.match(expression.strip()):
                P.add(rel, "workflow", "line %d: give the script ${{ %s }} through env: instead" % (line, expression.strip()))
    for machine in re.findall(r"^\s+runs-on:\s*(.+?)\s*$", without_comments(text), re.M):
        if not rules.GITHUBS_MACHINES.match(machine.strip("'\"")):
            P.add(rel, "workflow", "runs-on %s isn't one of GitHub's own machines" % machine)


def check_workflows(tree, P):
    for rel in tree.files():
        if rel.startswith(".github/workflows/") and rel.endswith(".yml"):
            text = tree.text(rel)
            if text is not None:
                check_workflow(rel, text, P)
    checks = ".github/workflows/checks.yml"
    if not tree.exists(checks):
        P.add(checks, "workflow", "missing: it holds the two checks the ruleset requires")
    else:
        text = tree.text(checks) or ""
        for name in ("Skills check", "Secret check"):
            if not re.search(r"^    name: %s$" % re.escape(name), text, re.M):
                P.add(checks, "workflow", "no job named %r (the ruleset requires that name)" % name)


# ---------------------------------------------------------------------------------------------
# Retirement (7.2.6)
# ---------------------------------------------------------------------------------------------

def parse_retired(text, P=None):
    """(retired slugs, retired kit paths) from the text of a retired.txt; bad lines go to P if given."""
    slugs, paths = set(), set()
    for number, line in enumerate((text or "").split("\n"), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^skills/[a-z0-9](?:-?[a-z0-9])*/[A-Za-z0-9][A-Za-z0-9._/-]*$", line):
            paths.add(line)
        elif valid_slug(line):
            slugs.add(line)
        elif P is not None:
            P.add("retired.txt", "retirement", "line %d: a slug, or skills/<slug>/<kit path>" % number)
    return slugs, paths


def read_retired(tree, P):
    """(retired slugs, retired kit paths) from retired.txt."""
    if not tree.exists("retired.txt"):
        return set(), set()
    return parse_retired(tree.text("retired.txt"), P)


def git_show(root, base, rel):
    try:
        done = subprocess.run(["git", "show", "%s:%s" % (base, rel)], cwd=root, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode("utf-8") if done.returncode == 0 else None


def commit_exists(root, base):
    """Whether `base` names a commit in this repository. A leading `-` is never passed to git."""
    if base.startswith("-"):
        return False
    try:
        done = subprocess.run(["git", "cat-file", "-e", base + "^{commit}"], cwd=root, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def check_retirement(tree, items, base, P, notes):
    retired_slugs, retired_paths = read_retired(tree, P)
    present = {i["slug"] for i in items}
    for slug in sorted(retired_slugs & present):
        P.add("retired.txt", "retirement", "%s is retired and still in the catalogue: a retired slug is never reused" % slug)
    if not base or set(base) <= {"0"}:
        notes.append("retirement check skipped: no base commit")
        return
    if not commit_exists(tree.root, base):
        P.add("--base", "retirement", "%r isn't a commit in this repository, so nothing can be compared with it "
              "(is the history fetched in full?)" % base)
        return
    # retired.txt only grows: every line the base had is still there.
    old_slugs, old_paths = parse_retired(git_show(tree.root, base, "retired.txt"))
    for line in sorted(old_slugs - retired_slugs) + sorted(old_paths - retired_paths):
        P.add("retired.txt", "retirement", "%s was retired on the base commit and is missing now: retired.txt only grows "
              "(otherwise a retired slug could come back)" % line)
    old = git_show(tree.root, base, "catalogue.json")
    if old is None:
        notes.append("retirement check skipped: the base commit has no catalogue.json")
        return
    try:
        old_items = json.loads(old)["items"]
    except (ValueError, KeyError, TypeError):
        notes.append("retirement check skipped: the base commit's catalogue.json can't be read")
        return
    current = {i["slug"]: i for i in items}
    for item in old_items:
        slug = item.get("slug")
        if slug not in current:
            if slug not in retired_slugs:
                P.add("catalogue.json", "retirement", "%s is gone from the catalogue and isn't in retired.txt (nothing disappears silently)" % slug)
            continue
        if item.get("kind") != "skill":
            continue
        kept = set(current[slug].get("meta", {}).get("kit", []))
        for path in item.get("meta", {}).get("kit", []):
            if path not in kept and ("skills/%s/%s" % (slug, path)) not in retired_paths:
                P.add("skills/%s/%s" % (slug, path), "retirement", "a kit path is never renamed or removed while its skill is in the catalogue (list it in retired.txt)")


# ---------------------------------------------------------------------------------------------
# check, write, hash
# ---------------------------------------------------------------------------------------------

def check(root, base=None, run_help_checks=True):
    """Every rule. Returns (problems as lines, notes)."""
    tree = Tree(root)
    P = Problems()
    notes = []
    check_layout(tree, P)
    for rel in tree.files():
        if rel in tree.symlinks:
            continue
        if is_text_file(rel) and tree.size(rel) <= rules.FILE_MAX_BYTES:  # a bigger one is already refused
            check_text_file(rel, tree.read(rel), P)
    skills = skill_slugs(tree)
    for slug in skills:
        fields = check_skill_doc(tree, slug, P)
        if fields is not None:
            check_examples(tree, slug, fields, P)
    for slug in agent_slugs(tree):
        check_agent_doc(tree, slug, skills, P)
    scripts = check_scripts(tree, P, run=run_help_checks)
    resolved = check_locks(tree, scripts, P)
    check_notices(tree, resolved, P)
    check_media(tree, P)
    check_templates(tree, P)
    check_kit_sizes(tree, P)
    check_workflows(tree, P)
    # What `write` would make must be what is there.
    existing = set(tree.files())
    problems, items = generate(tree)
    for path, rule, message in problems:
        P.add(path, rule, message)
    for rel in sorted(tree.changed()):
        if rel in existing:
            copy = rel.startswith("skills/") and not rel.endswith("/SKILL.md")
            P.add(rel, "generated", "is stale: " + RULE + (" (a shared file is changed in shared/, never in a skill)" if copy else ""))
        else:
            P.add(rel, "generated", "is missing: " + RULE)
    document = tree.text("catalogue.json")
    check_catalogue(json.loads(document), document, P)
    check_retirement(tree, items, base, P, notes)
    return P.lines(), notes


def write(root):
    tree = Tree(root)
    tree.files()
    if tree.symlinks:  # before anything is read or written
        return 1, ["%s: paths: a symbolic link (or a folder that is one): remove it; `write` never follows one" % link
                   for link in sorted(tree.symlinks)], []
    P = Problems()
    skills = skill_slugs(tree)
    for slug in skills:
        for p in read_skill(tree, slug)[2]:
            P.add("skills/%s/SKILL.md" % slug, "frontmatter", p)
    for slug in agent_slugs(tree):
        for p in read_agent(tree, slug)[2]:
            P.add("agents/%s/AGENT.md" % slug, "frontmatter", p)
    if len(P):
        return 1, P.lines(), []
    problems, _items = generate(tree)
    if problems:
        return 1, ["%s: %s: %s" % p for p in problems], []
    changed = tree.changed()
    problems = tree.write_all(changed)
    if problems:
        return 1, problems, []
    return 0, [], sorted(changed)


def hash_folder(root, folder):
    tree = Tree(root)
    _problems, items = generate(tree)
    wanted = folder.rstrip("/").replace(os.sep, "/")
    for item in items:
        if item["path"] == wanted:
            return item["contentHash"]
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Make the generated files of Hrizzup's skills repository, and check every rule.",
        epilog="Example: python3.12 tools/catalogue.py check --base origin/main",
    )
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("write", help="make the shared copies, generated sections, README table and catalogue.json")
    check_parser = commands.add_parser("check", help="verify every rule; exit 1 if any is broken")
    check_parser.add_argument("--base", default="", help="the base commit, for the retirement check")
    hash_parser = commands.add_parser("hash", help="print the contentHash of a skill or agent folder")
    hash_parser.add_argument("folder", help="skills/<slug> or agents/<slug>")
    args = parser.parse_args(argv)
    if args.command == "write":
        code, problems, changed = write(args.root)
        for line in problems:
            print(line)
        for rel in changed:
            print("wrote " + rel)
        if code == 0 and not changed:
            print("nothing to write: everything is already as `write` makes it")
        return code
    if args.command == "check":
        problems, notes = check(args.root, base=args.base)
        for line in problems:
            print(line)
        for note in notes:
            print("note: " + note)
        if problems:
            print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
            return 1
        print("ok: no problems")
        return 0
    value = hash_folder(args.root, args.folder)
    if value is None:
        print("no skill or starter agent at %s" % args.folder, file=sys.stderr)
        return 2
    print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
