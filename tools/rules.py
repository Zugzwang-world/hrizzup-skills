"""The repository's fixed values, in one place (docs/design.md, 3 to 9).

Standard library only. A new character, format code or pin is one line here and one test.
Nothing here holds a digest, a home-folder path or an email address: bad examples for the tests
are built from pieces where they are used, so these files never trip their own rules.
"""

from __future__ import annotations

import re

REPO = "Zugzwang-world/hrizzup-skills"
REPO_URL = "https://github.com/" + REPO
RAW_URL = "https://raw.githubusercontent.com/" + REPO + "/main"

# hrizzup's `social.formats` (new codes land there first), and the example story's ID.
FORMATS = (
    "breakdown",
    "timeline",
    "explainer",
    "meme",
    "audio-brief",
    "infographic",
    "translation",
    "source-check",
)
STORY_ID = "01a199e9-d180-75ec-8a81-134dd403419a"

# ---- the catalogue (hrizzup's docs/social/skills-catalogue.md, version 1) ----
CATALOGUE_VERSION = 1
CATALOGUE_MAX_BYTES = 1024 * 1024
KINDS = ("skill", "starter-agent")  # sorted in this order
ITEM_KEYS = (
    "slug", "kind", "name", "summary", "needs", "format", "path", "contentHash", "body", "meta",
)
SLUG = re.compile(r"^[a-z0-9](?:-?[a-z0-9])*$")
SLUG_MAX = 54
NAME_MAX = 60
SUMMARY_MAX = 300
NEEDS_MAX = 300
DESCRIPTION_MAX = 500
COMPATIBILITY_MAX = 500
BODY_MAX_CHARS = 20000
BODY_MAX_LINES = 500
AGENT_BODY_MAX = 6000
AGENT_SECTION_MAX = 1500
AGENT_SKILLS_MAX = 5

# ---- text (design 4.2) ----
# Printable ASCII and these marks only, in catalogue text (frontmatter values, SKILL.md, AGENT.md).
MARKS = "£°±·×–—‘’“”•…€₹←→−≈≤≥"
# Unicode categories no other text file may hold (LF and tab are the exceptions).
BAD_CATEGORIES = ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")
LICENCE_FILE = "OFL.txt"  # kept byte for byte as published: CR LF and trailing spaces allowed


def catalogue_char_ok(char: str, newline: bool = False) -> bool:
    """Whether one character may appear in catalogue text."""
    if char == "\n":
        return newline
    return " " <= char <= "~" or char in MARKS


# ---- the repository's layout (design 3) ----
TOP_LEVEL = (
    ".github", ".gitattributes", ".gitignore", "README.md", "NOTICES.md", "catalogue.json",
    "retired.txt", "docs", "shared", "skills", "agents", "tools",
)
TOP_LEVEL_DOT = (".github", ".gitattributes", ".gitignore")
GITIGNORE_LINES = (".DS_Store", "__pycache__/", "*.pyc", ".venv/", "out/")
# Names the working tree may hold that git ignores (the same five), so a local check matches CI.
IGNORED_NAMES = (".DS_Store", "__pycache__", ".venv", "out", ".git")
PATH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PATH_MAX = 200
FILE_MAX_BYTES = 25 * 1024 * 1024
KIT_MAX_BYTES = 3 * 1024 * 1024
README_START = "<!-- catalogue:start -->"
README_END = "<!-- catalogue:end -->"

# What a skill's folders may hold (the extension of each file, `.requirements.txt` counted whole).
SKILL_FOLDERS = {
    "scripts": (".py", ".lock", ".requirements.txt"),
    "assets": (".ttf", ".json", ".png", ".mplstyle", ".txt"),  # .txt is OFL.txt only
    "references": (".md",),
    "examples": (".md", ".json", ".txt", ".png", ".jpg", ".webp", ".mp4", ".m4a", ".srt"),
}
BINARY_EXTENSIONS = (".ttf", ".png", ".jpg", ".webp", ".mp4", ".m4a")
IMAGE_EXTENSIONS = (".png", ".jpg", ".webp")
TEXT_EXTENSIONS = (
    ".md", ".json", ".txt", ".srt", ".py", ".lock", ".mplstyle", ".yml", ".yaml",
)
SHARED_COPY_FOLDERS = ("references", "scripts", "assets")  # what `write` copies into a skill

# ---- SKILL.md and AGENT.md (design 4.1, 4.3, 4.5) ----
SKILL_SECTIONS = (
    "When to use", "What you need", "Get the kit", "Steps", "Post it", "Hrizzup's rules",
)
AGENT_SECTIONS = ("Purpose", "Voice", "Makes", "Never", "Cadence", "Style", "Skills")
# A sample's README opens with two lines (design 6): the fixed first line, then one that says which of the
# post's sources are real. The check reads the post's sources, so the second line can't go stale.
EXAMPLE_FIRST_LINE = "Illustrative: made from Hrizzup's example story, not real news."
EXAMPLE_SOURCES_PREFIX = "Sources: the post's "
EXAMPLE_SOURCES_ALL_EXAMPLE = "Sources: the post's sources are all example addresses."
EXAMPLE_HOSTS = ("example.com", "example.org", "example.net")  # reserved for examples (RFC 2606), and their subdomains
EXAMPLE_MACHINE = "a Mac with Apple silicon"
RULES_TEXT = (
    "Hrizzup basics, your locked skill file, applies to everything you make with this skill and "
    "wins over it. In particular: attach sources to what you post; say when something is unconfirmed; "
    "describe every image, and transcribe every video and every audio clip. Hrizzup's format guide "
    "also asks for a still image with every video and audio."
)
AGENT_INTRO_TEXT = (
    "A starter agent from Hrizzup's marketplace. To start from it, save each section below as "
    "your file of the same name, leave your categories and places empty until your owner chooses "
    "them, and ask your owner to attach the skills listed. Your owner reshapes all of it in your chat."
)
STYLE_DEFAULT = {
    "ink": "#111111", "paper": "#FFFFFF", "accent": "#111111",
    "display_font": "anton", "text_font": "atkinson-hyperlegible", "signature": "",
}
BODY_MAX_POST = 5000  # a text post's body
BODY_MAX_CAPTION = 1000  # a media post's body
POST_KINDS = ("text", "image", "video", "audio")
POST_SOURCES_MAX = 10
POST_DESCRIPTION_MAX = 1000
POST_TRANSCRIPT_MAX = 20000
# The sizes each format's picture may have (design 9). Video and audio posts name their still.
FORMAT_IMAGE_SIZES = {
    "meme": ((1080, 1080), (1080, 1350)),
    "infographic": ((1080, 1350), (1080, 1080)),
    "timeline": ((1080, 1350), (1080, 1080)),
}
STILL_SIZES = {"video": (1080, 1920), "audio": (1080, 1080)}

# ---- Hrizzup's text types (the API's, for a post's body, description and transcript) ----
# The agreement's `text` pattern (agreement/definitions/common.schema.json) forbids these code point
# ranges: controls, soft hyphen, joiners and direction marks, the private-use area and the like. Written as
# numbers, so no invisible character is typed into this file. The zero-width joiner (0x200D) isn't in it.
HIDDEN_RANGES = (
    (0, 31), (127, 159), (173, 173), (847, 847), (1536, 1541), (1564, 1564), (1757, 1757), (1807, 1807),
    (2192, 2193), (2274, 2274), (4447, 4448), (6068, 6069), (6155, 6159), (8203, 8204), (8206, 8207),
    (8232, 8233), (8234, 8238), (8288, 8303), (12644, 12644), (57344, 63743), (65024, 65037), (65279, 65279),
    (65440, 65440), (65520, 65531),
)
# What the database's `agreement.passes_code_checks` adds beyond the main plane (content_store.sql): the
# format, private-use and default-ignorable characters of the other planes, the tag characters among them.
ASTRAL_HIDDEN_RANGES = (
    (0x110BD, 0x110BD), (0x110CD, 0x110CD), (0x13430, 0x1343F), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD),
)
LF, TAB, ZWJ = 10, 9, 0x200D
VARIATION_SELECTORS = (0xFE00, 0xFE0F)


def hidden(char, allow=()):
    """Whether a character is one the agreement's text rule or its code checks forbid (`allow`: code
    points let through)."""
    code = ord(char)
    return code not in allow and any(low <= code <= high for low, high in HIDDEN_RANGES + ASTRAL_HIDDEN_RANGES)


def code_check_problems(name, value):
    """The agreement's other code checks, which both `plain_text` and `longText` pass: no two variation
    selectors in a row, a zero-width joiner only inside an emoji (never at an end, doubled, or next to an
    ASCII character or a new line), no new line at the very end."""
    found = []
    low, high = VARIATION_SELECTORS
    if any(low <= ord(a) <= high and low <= ord(b) <= high for a, b in zip(value, value[1:])):
        found.append("%s stacks variation selectors" % name)
    joiner = chr(ZWJ)
    if joiner in value:
        def ascii_or_lf(char):
            return char == "\n" or " " <= char <= "~"

        if value.startswith(joiner) or value.endswith(joiner) or joiner * 2 in value or any(
                (a == joiner and ascii_or_lf(b)) or (b == joiner and ascii_or_lf(a)) for a, b in zip(value, value[1:])):
            found.append("%s has a stray zero-width joiner" % name)
    if value.endswith("\n"):
        found.append("%s ends with a new line" % name)
    return found


def plain_text_problems(name, value, high):
    """The API's `plain_text` (a post's body, a description): 1 to `high` characters, new lines allowed,
    no control (but the new line) or invisible characters, no space or new line at either end, and the
    code checks."""
    if not isinstance(value, str):
        return ["%s isn't text" % name]
    found = []
    if not 1 <= len(value) <= high:
        found.append("%s is %d characters; 1 to %d" % (name, len(value), high))
    if value and (value[0] in " \n" or value[-1] in " \n"):
        found.append("%s has a space or new line at an end" % name)
    if any(hidden(c, allow=(LF,)) for c in value):
        found.append("%s has a control or invisible character (a new line is fine, a tab is not)" % name)
    return found + code_check_problems(name, value)


def long_text_problems(name, value, high):
    """The API's `longText` (a transcript): 1 to `high` characters, tabs and new lines but no other
    control character, no invisible character, and the code checks (so no final new line)."""
    if not isinstance(value, str):
        return ["%s isn't text" % name]
    found = []
    if not 1 <= len(value) <= high:
        found.append("%s is %d characters; 1 to %d" % (name, len(value), high))
    if any(hidden(c, allow=(LF, TAB, ZWJ, 0xFE0E, 0xFE0F)) for c in value):
        found.append("%s has a control or invisible character (only tabs and new lines are allowed)" % name)
    return found + code_check_problems(name, value)


# agreement.web_address (content_store.sql): https://, a host, an optional port and path, only the
# characters of RFC 3986, `%` only before two hex digits, at most 2,048 characters.
WEB_ADDRESS_SHAPE = re.compile(r"https://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::[0-9]{1,5})?(?:[/?#][^\x00-\x20\x7f-\x9f\\]*)?")
WEB_ADDRESS_CHARACTERS = re.compile(r"[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]*")
WEB_ADDRESS_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
WEB_ADDRESS_MAX = 2048


def web_address_problems(value):
    """Why a post's source isn't an `agreement.web_address` ([] when it is)."""
    if not isinstance(value, str):
        return ["isn't text"]
    found = []
    if len(value) > WEB_ADDRESS_MAX:
        found.append("is over %d characters" % WEB_ADDRESS_MAX)
    if not WEB_ADDRESS_SHAPE.fullmatch(value):
        found.append("must be https:// then a host (letters, digits, hyphens, dots), an optional port and a path")
    if not WEB_ADDRESS_CHARACTERS.fullmatch(value):
        found.append("holds a character a web address can't (plain ASCII letters, digits and the marks of RFC 3986 only)")
    if WEB_ADDRESS_BAD_PERCENT.search(value):
        found.append("has a % that isn't followed by two hexadecimal digits")
    return found


# ---- scripts (design 5) ----
REQUIRES_PYTHON = ">=3.12,<3.14"
STDLIB_REQUIRES_PYTHON = ">=3.10"
# Pinned 18 November 2026 (design 5): a release counts only if PyPI had it before this moment.
EXCLUDE_NEWER = "2026-11-15T00:00:00Z"
PINS = {
    "pillow": "13.0.0",
    "fonttools": "4.68.0",
    "matplotlib": "3.11.2",
    "numpy": "2.5.4",
    "kokoro-onnx": "0.6.1",
    "onnxruntime": "1.32.0",
    "faster-whisper": "1.2.1",
    "av": "18.1.0",  # not the newest: faster-whisper 1.2.1 can't use PyAV 19
    "imageio-ffmpeg": "0.8.1",
}
MODULE_PREFIX = "hrizzup_"  # shared modules: no header, no --help
SHARED_MODULES = ("hrizzup_media", "hrizzup_draw")
DRAW_TOP_IMPORTS = ("PIL", "fontTools")  # hrizzup_draw may import these at its top
# Who may import what (checked with ast; modules imported inside functions count too).
NETWORK_MODULES = ("socket", "ssl", "http", "urllib")
NETWORK_ALLOWED = ("check_links.py", "voice.py", "captions.py")
GPL_MODULES = ("kokoro_onnx", "phonemizer", "espeakng_loader")
GPL_ALLOWED = ("voice.py",)
FFMPEG_MODULES = ("subprocess", "imageio_ffmpeg")
FFMPEG_ALLOWED = ("hrizzup_media.py",)
OFFLINE_SCRIPTS = ("voice.py", "captions.py")  # take --offline
HELP_TAIL_LINES = 6
HELP_TIMEOUT_SECONDS = 30

# NOTICES.md: a package that ships code that isn't its own also needs rows for it, found by the
# words in the row's name (design 5, "Native extras").
NATIVE_NOTICES = {
    "imageio-ffmpeg": ("ffmpeg binary",),
    "av": ("ffmpeg libraries", "x264 and x265", "codec and system libraries"),  # av's wheel also carries the codecs it is built with
    "espeakng-loader": ("espeak-ng",),
    "kokoro-onnx": ("kokoro-82m",),
    "faster-whisper": ("whisper base.en",),
    # the Linux wheel carries the OpenMP runtime, and libctranslate2 has oneMKL, oneDNN, spdlog and the CUDA runtime compiled in (the
    # macOS one, Ruy and spdlog)
    "ctranslate2": ("libgomp", "compiled ctranslate2"),
    "onnxruntime": ("compiled onnxruntime",),  # the wheel's ThirdPartyNotices.txt lists what is compiled in
    # numpy's wheel carries a linear-algebra build and the compiler's runtime libraries; matplotlib's carries its own fonts
    # (licence files in numpy's dist-info and in matplotlib's mpl-data/fonts/ttf, read 18 November 2026).
    "numpy": ("openblas", "lapack", "gcc runtime", "libquadmath"),
    "matplotlib": ("dejavu", "stix", "freetype matplotlib", "harfbuzz matplotlib", "libraqm matplotlib", "sheenbidi", "qhull",
                   "bakoma", "colorbrewer", "last resort"),
    # Pillow's wheels carry the image libraries it is built on (the wheel's own SBOM and licence file, read 18 November
    # 2026 in the macOS arm64 and Linux x86_64 wheels).
    "pillow": ("freetype pillow", "harfbuzz pillow", "raqm pillow", "fribidi pillow", "libjpeg pillow", "libpng pillow",
               "libwebp pillow", "zlib pillow", "lcms2 pillow", "libtiff pillow", "openjpeg pillow", "libavif pillow",
               "brotli pillow", "xz pillow", "libxcb pillow", "libxau pillow", "libzstd pillow", "libimagequant pillow"),
}
NOTICES_COLUMNS = ("Name", "Version", "Licence", "Home", "How it's used", "Used by")
GPL_WORDS = ("gpl",)  # a licence naming GPL but not LGPL
BUNDLED_WORD = "bundled"

# ---- a public repository (design 4.2, 5) ----
# Built from pieces so this file doesn't match what it looks for.
_HOME = r"(?<![A-Za-z0-9._-])(?:/Use[r]s/|/hom[e]/|[A-Za-z]:\\{1,2}Use[r]s\\{1,2})[A-Za-z0-9_.-]"
HOME_PATH = re.compile(_HOME)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
NOREPLY_SUFFIX = "@users.noreply.github.com"

# gitleaks 8.30.1's generic-api-key rule reads these words as a key's name (default config).
DIGEST_WORDS = (
    "access", "auth", "api", "credential", "creds", "key", "passwd", "password", "secret", "token",
)
# The shape that rule flags, narrowed to a 64-hex digest: a key word, up to 20 name characters, a
# separator, then the digest. A pre-flight only: the Secret check stays the authority.
DIGEST_TRAP = re.compile(
    r"""(?i)(?:access|auth|api|credential|creds|key|passw(?:or)?d|secret|token)"""
    r"""[ \t\w.-]{0,20}[\s'"]{0,3}(?:=|>|:{1,3}=|\|\||:|=>|\?=|,)[`'"\s=]{0,5}[0-9a-f]{64}(?![0-9a-f])"""
)

# ---- workflows (design 7.2, ported from hrizzup's test_public_repo.py) ----
SAFE_IN_SCRIPTS = re.compile(
    r"^(?:github\.(?:sha|run_id|run_number|run_attempt|repository|repository_owner|workspace)"
    r"|runner\.(?:temp|os|arch)|matrix\.[\w-]+)$"
)
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
GITHUBS_MACHINES = re.compile(r"^(?:ubuntu|windows|macos)-[\w.-]+$")
FORBIDDEN_TRIGGERS = ("pull_request_target", "workflow_run")
# claude.ai and the Skills API refuse a skill whose `name` holds these words, and XML tags (any `<` or
# `>`) in a skill's `name` or `description` (Anthropic's Agent Skills documentation).
RESERVED_NAME_WORDS = ("anthropic", "claude")
