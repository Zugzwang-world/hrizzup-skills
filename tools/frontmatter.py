"""The strict frontmatter of SKILL.md and AGENT.md (docs/design.md, 4.1).

A small subset of YAML, so every SKILL.md also loads in claude.ai and the Skills API: line 1 is
`---`, the next `---` ends it, and in between only these lines, in this order, every value in
double quotes with no `"` or `\\` inside:

    name: "<folder name>"
    description: "..."
    compatibility: "..."             skills with a scripts/ folder only
    metadata:
      hrizzup-name: "..."
      hrizzup-summary: "..."
      hrizzup-needs: "..."           skills
      hrizzup-format: "..."          skills, left out for a general creator tool
      hrizzup-skills: "a b c"        starter agents, in place of needs and format

Then one blank line and `# <hrizzup-name>`. Standard library only.
"""

from __future__ import annotations

import re

import rules

SKILL = "skill"
AGENT = "agent"

# (key, indent, required, max length), in the order the lines must come.
_SKILL_LINES = (
    ("name", 0, True, rules.SLUG_MAX),
    ("description", 0, True, rules.DESCRIPTION_MAX),
    ("compatibility", 0, False, rules.COMPATIBILITY_MAX),
    ("metadata", 0, True, None),
    ("hrizzup-name", 2, True, rules.NAME_MAX),
    ("hrizzup-summary", 2, True, rules.SUMMARY_MAX),
    ("hrizzup-needs", 2, True, rules.NEEDS_MAX),
    ("hrizzup-format", 2, False, 40),
)
_AGENT_LINES = (
    ("name", 0, True, rules.SLUG_MAX),
    ("metadata", 0, True, None),
    ("hrizzup-name", 2, True, rules.NAME_MAX),
    ("hrizzup-summary", 2, True, rules.SUMMARY_MAX),
    ("hrizzup-skills", 2, True, 400),
)
_LINE = re.compile(r'^( *)([a-z][a-z-]*):(?: (.*))?$')
_QUOTED = re.compile(r'^"([^"\\]*)"$')


def parse(text: str, kind: str, folder: str):
    """Read the frontmatter of a SKILL.md or AGENT.md.

    Returns (fields, body_start, problems): `fields` maps each key to its value (`metadata` left
    out), `body_start` is the index of the `# <name>` line in `text.split("\\n")`, and `problems`
    lists everything wrong, in plain words. `fields` is None when it can't be read at all.
    """
    spec = _SKILL_LINES if kind == SKILL else _AGENT_LINES
    problems: "list[str]" = []
    lines = text.split("\n")
    if lines[0] != "---":
        return None, 0, ["line 1 must be `---`, which opens the frontmatter"]
    try:
        close = lines.index("---", 1)
    except ValueError:
        return None, 0, ["the frontmatter never closes: no second `---` line"]
    fields: "dict[str, str]" = {}
    position = 0  # how far through `spec` we are
    for number, line in enumerate(lines[1:close], start=2):
        if "\t" in line:
            problems.append("line %d: a tab; indent with spaces" % number)
            continue
        found = _LINE.match(line)
        if not found:
            problems.append("line %d: not a `key: \"value\"` line (a value goes on one line, in double quotes)" % number)
            continue
        indent, key, rest = len(found.group(1)), found.group(2), found.group(3)
        slot = next((i for i in range(position, len(spec)) if spec[i][0] == key), None)
        if slot is None:
            if any(s[0] == key for s in spec):
                what = "`%s` is out of order or repeated" % key
            else:
                what = "`%s` isn't a key this file takes" % key
            problems.append("line %d: %s (the keys, in order: %s)" % (number, what, ", ".join(s[0] for s in spec)))
            continue
        for skipped in range(position, slot):
            if spec[skipped][2]:
                problems.append("`%s` is missing before line %d" % (spec[skipped][0], number))
        position = slot + 1
        want_indent, max_length = spec[slot][1], spec[slot][3]
        if indent != want_indent:
            problems.append("line %d: `%s` is indented %d spaces, not %d" % (number, key, indent, want_indent))
        if key == "metadata":
            if rest is not None:
                problems.append("line %d: `metadata:` takes its values on the lines below it" % number)
            continue
        quoted = _QUOTED.match(rest) if rest is not None else None
        if not quoted:
            reason = "no value"
            if rest is not None:
                reason = "no double quotes round it"
                if "\\" in rest:
                    reason = "a backslash in it"
                elif rest.count('"') > 2:
                    reason = "a double quote inside it"
            problems.append("line %d: the value of `%s` must be one \"double-quoted\" string (%s)" % (number, key, reason))
            continue
        value = quoted.group(1)
        fields[key] = value
        problems.extend(_value_problems(key, value, max_length))
    for skipped in range(position, len(spec)):
        if spec[skipped][2]:
            problems.append("`%s` is missing" % spec[skipped][0])
    if "name" in fields and fields["name"] != folder:
        problems.append("`name` is %r but the folder is %r: they must match" % (fields["name"], folder))
    if "name" in fields and not rules.SLUG.match(fields["name"]):
        problems.append("`name` %r isn't a slug (lower case, digits and single hyphens)" % fields["name"])
    if fields.get("hrizzup-format") is not None and fields["hrizzup-format"] not in rules.FORMATS:
        problems.append("`hrizzup-format` %r isn't one of Hrizzup's format codes" % fields["hrizzup-format"])
    if kind == AGENT and "hrizzup-skills" in fields:
        slugs = fields["hrizzup-skills"].split(" ")
        if not all(rules.SLUG.match(s) for s in slugs) or len(slugs) > rules.AGENT_SKILLS_MAX:
            problems.append("`hrizzup-skills` is one to %d slugs with single spaces between" % rules.AGENT_SKILLS_MAX)
        elif len(set(slugs)) != len(slugs):
            problems.append("`hrizzup-skills` names a skill twice")
    # After the frontmatter: one blank line, then `# <hrizzup-name>`.
    body_start = close + 2
    title = fields.get("hrizzup-name")
    if len(lines) <= body_start or lines[close + 1] != "":
        problems.append("one blank line must follow the closing `---`")
    elif title is not None and lines[body_start] != "# " + title:
        problems.append("the line after the blank must be `# %s` (the `hrizzup-name`)" % title)
    return fields, body_start, problems


def _value_problems(key: str, value: str, max_length):
    found = []
    if value == "":
        found.append("`%s` is empty" % key)
    if value != value.strip(" "):
        found.append("`%s` starts or ends with a space" % key)
    bad = sorted({c for c in value if not rules.catalogue_char_ok(c)})
    if bad:
        found.append("`%s` holds %s, which catalogue text can't (printable ASCII and a short list of marks)"
                     % (key, " ".join("U+%04X" % ord(c) for c in bad)))
    if max_length is not None and len(value) > max_length:
        found.append("`%s` is %d characters; at most %d" % (key, len(value), max_length))
    return found
