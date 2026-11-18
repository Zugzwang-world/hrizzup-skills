# hrizzup-skills: the design

R10's expert wrote this before any code (Round 6, 18 November 2026). The builder follows it, and `tools/catalogue.py check` enforces most of it. The builder's M1 probes (12) settled the pins and the models' digests the same day and amended sections 3 to 7, 10, 12 and 14 to match; what a rule needed that the first draft left open is written where the rule is. The format of `catalogue.json` is defined in hrizzup's `docs/social/skills-catalogue.md`, which wins over this note.

## 1. Decisions

- **Folders:** one self-contained folder per skill (`skills/<slug>/`, [Agent Skills](https://agentskills.io/specification) format) and per starter agent (`agents/<slug>/AGENT.md`).
- **Frontmatter:** Hrizzup's fields sit under `metadata` as strings, in a strict YAML subset, so every `SKILL.md` also loads in claude.ai and the Skills API.
- **Generated, never hand-copied:** shared files, the catalogue, two `SKILL.md` sections and the README's table. The check fails on drift.
- **Scripts:** Python 3.12, PEP 723, exact pins for every package (a lock and a hashed pip export beside each command with packages), `uv run`.
- **Media:** Pillow draws every image and video frame, text included. FFmpeg (shipped by imageio-ffmpeg) only encodes, levels and muxes, using built-in filters. Voice: Kokoro-82M. Captions and voice check: faster-whisper. Loudness: −16 LUFS.
- **Templates:** original and plain (black, white, the agent's own style), since design comes only from the design chat.
- **CI:** offline, standard library only. Required checks: "Skills check" and "Secret check".

## 2. Rejected

| Alternative | Why not |
|---|---|
| skills-ref in CI | "Demonstration purposes only", and needs packages; run locally (12) |
| Symlinks, or one shared folder | Raw downloads get a link's text; folders stop standing alone |
| Git LFS | 1 GB of free bandwidth a month breaks raw downloads |
| FFmpeg drawtext, subtitles, zoompan | Missing from common builds; zoompan jitters |
| MoviePy | Breaking changes, for what Pillow and FFmpeg do directly |
| Piper | GPL itself; few cleanly licensed voices |
| Whisper's words as the transcript | The script is what was said; Whisper only times and checks it |
| A required Linux kit run | PyPI on every pull request; run by hand instead (7.4) |
| Hashing the folder's files | Misses fields Hrizzup stores; the hash covers the catalogue item |

## 3. Layout and names

```text
README.md, NOTICES.md (table: Name | Version | Licence | Home | How it's used | Used by)
catalogue.json (generated); retired.txt (retired slugs and kit paths, one a line)
.gitattributes (first line: * -text); .gitignore (.DS_Store, __pycache__/, *.pyc, .venv/, out/)
docs/design.md
shared/  rules.md, agent-intro.md, references/sizes.md, scripts/{hrizzup_media,hrizzup_draw,voice,still}.py
         (each command with packages beside its own <name>.py.lock and <name>.requirements.txt, 5),
         assets/fonts/anton/{Anton-Regular.ttf,OFL.txt},
         assets/fonts/atkinson-hyperlegible/{AtkinsonHyperlegible-Regular.ttf,AtkinsonHyperlegible-Bold.ttf,OFL.txt}
skills/<slug>/  SKILL.md, scripts/ (.py, <name>.py.lock, <name>.requirements.txt), assets/ (.ttf, OFL.txt, .json, .png, .mplstyle),
                references/ (.md), examples/ (.md .json .txt .png .jpg .webp .mp4 .m4a .srt)
agents/<slug>/  AGENT.md only
tools/  catalogue.py (write | check | hash), rules.py, frontmatter.py, test_*.py
.github/workflows/  checks.yml, kits-linux.yml
```

- **Paths:** ASCII parts matching `^[A-Za-z0-9][A-Za-z0-9._-]*$` (the top level's `.github`, `.gitattributes` and `.gitignore` excepted), at most 200 characters; none differing only in case; no symlinks (`write` and `check` never follow one: if the tree holds a link, or a folder that is one, `write` stops before reading or writing anything, and every file it writes is checked to stay inside the repository); no file over 25 MiB; nothing else at the top level; no part containing a word the Secret check reads as a key's name (`rules.DIGEST_WORDS`, 5), so `catalogue.json`'s `kitSha256` is never flagged.
- **Fonts:** from google/fonts at `cc39c4c2c304bc368c9b7c311ea2bcc6013299fe` (confirmed there 18 November 2026, each against GitHub's own listing for that commit by size and git blob ID; SHA-256 computed from the verified download):

  | File (under `ofl/`) | Bytes | SHA-256 |
  |---|---|---|
  | `anton/Anton-Regular.ttf` | 170,812 | `a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab` |
  | `anton/OFL.txt` | 4,484 | `ee67e6ee22790b7929f1a3769ca2801d565c64b5a9096942c1adf5596de9c9e4` |
  | `atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf` | 54,348 | `7fb917c89019896d0b52ee84b7cbb3304c18cb90b19a62f5e32712bd23e97669` |
  | `atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf` | 55,256 | `5a3b0c8cc8ca545155150b4512a1fa248298df121c50d6557e651e61fbdab92f` |
  | `atkinsonhyperlegible/OFL.txt` | 4,352 | `f32d22b3908fcad2c86a74000614ec22e6a7f66ea7e867e616026a27aebdc143` |

  Anton's `OFL.txt` has CR LF line endings and Atkinson's has trailing spaces: both are kept byte for byte (4.2). **Glyph gaps (probe 4):** Atkinson Hyperlegible has no `₹`, `←` or `→`, which 4.2 allows as text; Anton has all of 4.2's marks. `hrizzup_draw` refuses a glyph a font lacks (8.1), so a text-font slot can't draw them: M2's guides tell agents to write "Rs" or "INR" and "to" in drawn text.
- **Slugs:** 1–54 characters, `^[a-z0-9](?:-?[a-z0-9])*$`, unique across both kinds, never reused. Skills: `breakdown`, `timeline`, `explainer-video`, `meme`, `audio-brief`, `infographic`, `translate`, `source-check`. Starter agents: `explainer`, `meme-maker`, `analyst`, `audio-brief-agent`, `translator`, `source-checker` (a starter agent whose natural slug is a skill's adds `-agent`).
- **`tools/rules.py`:** `REPO = "Zugzwang-world/hrizzup-skills"`; hrizzup's eight format codes (`breakdown`, `timeline`, `explainer`, `meme`, `audio-brief`, `infographic`, `translation`, `source-check`; new ones land there first); the example story's ID `01a199e9-d180-75ec-8a81-134dd403419a`; the catalogue's limits, the allowed marks, the pins (5), the key words (5, Digests) and the workflow rules. **Section 9's limits** (Hrizzup's and this repository's budgets) and the FFmpeg allowlist live in `shared/scripts/hrizzup_media.py`, because the scripts import them there; `tools/` loads that same file, so there is one copy of each number.

## 4. SKILL.md and AGENT.md

### 4.1 Frontmatter

Line 1 is `---`; the frontmatter ends at the next `---`, then one blank line and `# <hrizzup-name>`. Only these lines, in this order:

```text
name: "<slug>"
description: "<what it does, and when to use it>"          1–500 characters
compatibility: "<exact technical needs>"                   1–500; present when scripts/ exists, and only then
metadata:
  hrizzup-name: "<display name>"                           1–60
  hrizzup-summary: "<the marketplace line>"                1–300
  hrizzup-needs: "<the spec's needs wording, or Nothing>"  1–300
  hrizzup-format: "<format code>"                          absent for a general tool
```

`AGENT.md` has `name`, then `metadata:` with `hrizzup-name`, `hrizzup-summary` and `hrizzup-skills` (slugs, single spaces). Every value is double-quoted, with no `"` or `\` inside (use ’ “ ”). `name` is the folder's name. No `license` until the legal team picks one.

### 4.2 Text rules

- **Catalogue text** (frontmatter values; all of `SKILL.md` and `AGENT.md`): printable ASCII, LF inside bodies, and `£ ° ± · × – — ‘ ’ “ ” • … € ₹ ← → − ≈ ≤ ≥` only. No tab, CR, or space at a value's ends; exactly one final LF; lengths in code points. This sits inside every Hrizzup text rule; a new character is one line in `rules.py` plus a test.
- **Other text files:** UTF-8, no BOM, LF, one final LF; nothing in categories Cc (but LF and tab), Cf, Co, Cs, Cn, Zl or Zp. The one exception is `OFL.txt`, kept byte for byte as google/fonts publishes it (CR LF line endings and trailing spaces allowed, no final LF needed; the rest of the rule holds). `.gitattributes` starts `* -text`, so git never rewrites a line ending.
- **A public repository** (every text file, `docs/` and the workflows included): no home-folder path (`/Users/` or `/home/` followed by a name, `C:\Users\` followed by a name) and no email address but GitHub's `…@users.noreply.github.com`. **Binary samples** can't be read by `check`: 6 has the step that catches a path in one.
- **`examples/post.json`:** `body` and `description` as the API's `plain_text` (any visible character in any script, new lines inside, none at either end, no tab, no invisible character), `transcript` as `longText` (tabs and new lines, no other control or invisible character, no final new line). Both are ported from the agreement's `text` pattern and the API's `longText` (`rules.HIDDEN_RANGES`, as numbers), so an original-language word in a translation passes; the catalogue allowlist above is for SKILL.md and AGENT.md only.

### 4.3 A skill's body

In this order, with these exact headings:

1. `# <hrizzup-name>` and 1–3 sentences.
2. `## When to use`.
3. `## What you need`: the needs line; Python 3.12 with uv (`pip install uv`); what downloads on first run, and its size; without uv, make a virtual environment and install the exact, hash-checked set from the script's exported file, then run the script with that environment's Python: `python3.12 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes -r scripts/<name>.requirements.txt`, `.venv/bin/python scripts/<name>.py` (5). Every script with packages gets its own such line, naming its file.
4. `## Get the kit` (generated; only when there are kit files).
5. `## Steps`, numbered: pin the story and read its brief; go on only if this adds something "Already on the desk" lacks; make it; run its checks.
6. Optional sections (script shape, good and bad examples).
7. `## Post it`: kind, format code, caption limit, what the upload needs. No API paths; those stay in Hrizzup's skill file and format guide.
8. `## Hrizzup's rules`, generated from `shared/rules.md`, exactly:

> Hrizzup basics, your locked skill file, applies to everything you make with this skill and wins over it. In particular: attach your sources; say what's unconfirmed; describe every image you upload; give every video and audio its full transcript and a still image.

Every `scripts/…`, `assets/…` or `references/…` path named must exist; commands run from the skill's folder.

### 4.4 Generated and shared

`write`, in order (`check` compares the same):

1. Shared copies: `skills/<slug>/<p>` is overwritten from `shared/<p>` when that exists (a skill opts in by holding the file).
2. Sections, each up to the next `## `: `## Get the kit`, `## Hrizzup's rules`, and each agent's introduction (`shared/agent-intro.md`, after its `# ` line) and `## Skills`.
3. The README's table, between `<!-- catalogue:start -->` and `<!-- catalogue:end -->`.
4. `catalogue.json`.

`## Get the kit` reads:

```text
This skill's kit is the folder skills/<slug> of https://github.com/Zugzwang-world/hrizzup-skills (public: no account needed). If its files aren't next to this file, either:
- run `git clone --depth 1 https://github.com/Zugzwang-world/hrizzup-skills.git` and work in hrizzup-skills/skills/<slug>; or
- download each file below from https://raw.githubusercontent.com/Zugzwang-world/hrizzup-skills/main/skills/<slug>/<file>, keeping its path.
Run every command in this skill from that folder. When this skill's version on Hrizzup changes, get the kit again.
Files: `<path>`, `<path>`, …
A real sample made with it, and how: https://github.com/Zugzwang-world/hrizzup-skills/tree/main/skills/<slug>/examples
```

### 4.5 A starter agent's body

`# <hrizzup-name>`; the introduction ("A starter agent from Hrizzup's marketplace. To start from it, save each section below as your file of the same name, leave your categories and places empty until your owner chooses them, and ask your owner to attach the skills listed. Your owner reshapes all of it in your chat."); then `## Purpose`, `## Voice`, `## Makes`, `## Never`, `## Cadence`, `## Style` (one fenced `json` block, 8.1) and `## Skills` (generated). Sections 1–1,500 characters; the body at most 6,000.

## 5. Scripts

One file per command, run from the skill's folder as `uv run scripts/<name>.py`; shared modules are imported as siblings. `hrizzup_media.py` (standard library) and `hrizzup_draw.py` are modules, not commands: no header, no `--help`, and `hrizzup_draw` may import Pillow and fontTools at its top. The rules below are for commands. The header:

```python
# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
```

- **Pins:** each dependency `==` its newest release at least 3 days old on the pinning day; `exclude-newer` is that day minus 3 days; one pin per package and one `exclude-newer` across the repository (checked). Standard-library-only scripts: `dependencies = []`, `requires-python = ">=3.10"`.

  **Pinned 18 November 2026:** `exclude-newer = "2026-11-15T00:00:00Z"`: a release counts only if PyPI had it before that moment. All of these resolve together on Python 3.12 and 3.13 (`uv lock --script` on one header holding them all: 42 packages), and each pin below is the newest release before that moment, except where the note says so. `tools/rules.py` holds the same table (`EXCLUDE_NEWER`, `PINS`), and `check` fails a header that names another date, another version, or a package not in it, so no later milestone re-pins. A new package or a new date is one change to `rules.py`, this table and every lock.

  | Package | Pin | Released | Note |
  |---|---|---|---|
  | `pillow` | `13.0.0` | 16 Oct 2026 | Pillow 13 deprecates `Image.getdata` (use `get_flattened_data`) |
  | `fonttools` | `4.68.0` | 27 Oct 2026 | |
  | `matplotlib` | `3.11.2` | 11 Sep 2026 | |
  | `numpy` | `2.5.4` | 10 Oct 2026 | 2.5.5 came at 21:30 UTC on 15 Nov, after the cut-off; leave it |
  | `kokoro-onnx` | `0.6.1` | 19 Aug 2026 | needs `phonemizer` and `espeakng-loader` (GPL) |
  | `onnxruntime` | `1.32.0` | 13 Nov 2026 | |
  | `faster-whisper` | `1.2.1` | 31 Oct 2025 | |
  | `av` | `18.1.0` | 12 Aug 2026 | **Not the newest.** faster-whisper 1.2.1 calls `av.open(..., metadata_errors=…)`, which PyAV 19.0.0 and later refuse (`TypeError`); 18.1.0 is the newest that takes it. A direct pin in `captions.py`'s header, so a re-lock can never move it. Revisit when faster-whisper does |
  | `imageio-ffmpeg` | `0.8.1` | 3 Nov 2026 | its FFmpeg is GPL (the GPL bullet below) |

  Transitive packages (ctranslate2 4.9.0, tokenizers, huggingface-hub, phonemizer 3.6.0, espeakng-loader 0.2.4 and the rest) come from the locks, not from this table.
- **Locks (every transitive pin):** a header pins only its direct packages, so every command whose `dependencies` isn't empty carries, beside it, two files uv makes from its header, run from the script's folder (probed 18 November 2026 with uv 0.13.1; commands from `uv help lock` and `uv help export`):

  ```text
  uv lock --script <name>.py
  uv export --script <name>.py --format requirements.txt --locked -o <name>.requirements.txt
  ```

  - `<name>.py.lock` is uv's own file, written beside the script by `uv lock --script` (its name and place are uv's): the whole resolved set with every file's hash. `uv run scripts/<name>.py` reuses it, re-locking only if the header changed.
  - `<name>.requirements.txt` is the same set as a pip requirements file with hashes and environment markers (`--locked` stops a stale lock). It is for a creator without uv: 4.3's `pip install --require-hashes -r`. Probed: it installed on a clean Python 3.12 virtual environment and ran faster-whisper.
  - Shared scripts keep both in `shared/scripts/` and they are copied like the script (4.4); both are in the kit and its hashes. Re-lock whenever a header or `exclude-newer` changes.
  - `check` reads them offline (`tomllib`): the lock's `manifest` equals the header's dependencies, its `exclude-newer` and `requires-python` equal the header's; the requirements file lists exactly the lock's packages and versions, each with at least one `--hash` that the lock holds; across the repository one version of each package; and `NOTICES.md` has a row for every locked package (same name and version).
  - **Native extras:** a few packages ship code that isn't theirs, so `rules.NATIVE_NOTICES` also asks for these rows, matched by the words in their name: `imageio-ffmpeg` needs one for "FFmpeg binary", `av` for "FFmpeg libraries", `espeakng-loader` for "espeak-ng", `kokoro-onnx` for "Kokoro-82M" and `faster-whisper` for "Whisper base.en" (the models, 10).
- **Imports:** at the top only the standard library and `hrizzup_media`; `hrizzup_draw` and packages inside functions, where an `ImportError` exits 3 with the install line. So `--help` and the check need nothing installed.
- **Command line:** argparse flags, never a prompt; `--help` ends with an example; outputs only to `--out`, never over an input; logs to stderr; the last stdout line is one JSON object `{"ok", "outputs": [{"path", "bytes", "width", "height", "seconds"}], "checks", "problem"}`.
- **Exit codes:** 0 made and checked; 1 the output failed a Hrizzup limit or quality check (nothing left behind; the JSON says what to change); 2 bad input; 3 a missing tool, package or model.
- **Every media script checks its own output** with `hrizzup_media`.
- **FFmpeg only through `hrizzup_media`'s builders** (`encode_video`, `loudnorm_measure`, `loudnorm_apply`, `decode_clip`). Allowlist: filters `loudnorm`, `aresample`, `scale`, `crop`, `fps`, `format`, `setsar`; encoders `libx264`, `h264_videotoolbox`, `libopenh264`, `aac`, `pcm_s16le`; formats `rawvideo`, `mp4`, `ipod`, `wav`, `null`.
  `subprocess` and `imageio_ffmpeg` appear only in `hrizzup_media` (the FFmpeg bullet above); no command calls `input()`; `--help` of every command ends with an example (the word "Example" and the command's own file name appear in its last lines); `voice.py` and `captions.py` take `--offline`.
- **Network:** only `check_links.py`, and first runs of `voice.py` and `captions.py` for models (`--offline` refuses): `check` lets only those three scripts import `socket`, `ssl`, `http` or `urllib` (not `hrizzup_media`, which is copied into every skill; where the model downloader lives is M4's call).
- **GPL:** only `voice.py` imports `kokoro_onnx` (phonemizer and espeak-ng are GPL-3.0), checked with `ast` (it names `kokoro_onnx`, `phonemizer` and `espeakng_loader`). **The FFmpeg binary imageio-ffmpeg installs is GPL too** (probe 1: FFmpeg 9.0, built with `--enable-gpl`, x264 and x265 included; `ffmpeg -L` says GPL version 2 or later). It is never copied into this repository: it installs in the creator's setup and runs as a separate program, only through `hrizzup_media`. `av`'s own FFmpeg libraries report "LGPL version 3 or later" (`avcodec_license()` on its 18.1.0 macOS wheel, libavcodec 62.28.102). `NOTICES.md` says "installed by the creator's setup", never "bundled", for every GPL row (checked). Whether this is enough is the legal team's call (14.2).
- **Digests** (a SHA-256 is 64 hex characters; gitleaks 8.30.1's `generic-api-key` rule reads `token` in `tokenizer.json` as a key's name and flags `"tokenizer.json": "<digest>"`, probed on 18 November 2026 over 19 shapes). So: digests are stored only (a) in tables in `.md` files, (b) in uv's lock and requirements files, (c) in `catalogue.json`'s `kitSha256` (fixed by the catalogue's format), and (d) in scripts and `rules.py` as tuples with **the digest first and the name after** (`("<digest>", <bytes>, "tokenizer.json")`), never as `"<name>": "<digest>"` in a JSON object or dict, a name-then-digest tuple or list, or a `name: digest` line. No path in the repository contains `access`, `auth`, `api`, `credential`, `creds`, `key`, `passwd`, `password`, `secret` or `token`, in any case (`rules.DIGEST_WORDS`), so a kit path in `kitSha256` can't look like a key's name. `check` also scans every text file for the shape gitleaks flags (a 64-hex digest right after such a word and a `:`, `=`, `=>` or `,`) as a pre-flight; it matched gitleaks's findings exactly on those 19 shapes, but the Secret check stays the authority. No allowlist, ever: that would loosen the check.
- **Command lines only grow:** new flags have defaults; no flag or kit file is renamed or removed while its skill is in the catalogue (unless in `retired.txt`), so edited copies keep working.

## 6. Examples

Each skill's `examples/` proves it, made on a Mac from Hrizzup's example story (the Delhi NCR smog story in hrizzup's `agreement/examples/`, through its brief). Every skill has a `README.md` and a `post.json` there (`check` fails without them); a skill with command scripts shows each one's command in the README. A picture's size is also checked against its format (8.1 and 9): a meme 1080 × 1080 or 1080 × 1350, an infographic or a timeline card 1080 × 1350 or 1080 × 1080, a video's still 1080 × 1920, an audio's still 1080 × 1080; a video 1080 × 1920.

- **`README.md`:** first line "Illustrative: made from Hrizzup's example story, not real news; its sources are example addresses."; then the input, every command as run, the versions (Python, uv, packages, FFmpeg, models), the machine ("a Mac with Apple silicon"), the date, the results (bytes, dimensions, seconds, loudness), and every other file's name.
- **`post.json`**, the post without `requestId`:

  ```json
  { "storyId": "01a199e9-d180-75ec-8a81-134dd403419a", "kind": "image", "format": "meme",
    "body": "…", "sources": ["https://example.com/…"],
    "media": { "file": "meme.png", "description": "…" } }
  ```

  Video and audio: `media` is `{"file", "transcript", "still": {"file", "description"}}`, the transcript being the script's shown text. Checked: the story's ID; the skill's format; `body` 1–5,000 characters (text) or 1–1,000 (media); at most 10 `web_address` sources; `description` 1–1,000; `transcript` 1–20,000; files within section 9 and the repository's budgets (an image 2 MiB, audio 5 MiB, video 25 MiB).
- Samples are never in the kit or the hash. Remake one only when the output visibly changes: history keeps every copy.
- A sample says only what the updates say. A joke may exaggerate a feeling, never invent a fact.
- **Before committing a binary sample** (`.png`, `.jpg`, `.webp`, `.mp4`, `.m4a`; fonts too), run `strings <file> | grep -E "/Use[r]s/|/hom[e]/"` and see it print nothing (the bracketed letters keep this line from matching itself, as the public-repository rule of 4.2 requires). FFmpeg can write an `encoder` tag and Pillow EXIF, and a path hides in either: samples are made without metadata (5, 8.1), and this is how a slip is caught. The builder records "checked" in the sample's `README.md`.

## 7. The check

### 7.1 Commands

```text
python3.12 tools/catalogue.py write | check [--base <sha>] | hash <folder>
python3.12 -m unittest discover -s tools -p 'test_*.py'
```

Standard library only, offline, Python 3.12 or later (this Mac's `python3` is 3.9: use `python3.12` or `uv run tools/catalogue.py`). `check` prints `path: rule: message` per problem and exits 1 if any. Under Python older than 3.12 `catalogue.py` still parses (a test parses `tools/*.py` as Python 3.9) and exits 2 with the command to use, before it imports anything else.

**The file list** comes from `git ls-files --cached --others --exclude-standard` (what a pull request would hold, so `__pycache__`, `.venv`, `out/` and `.DS_Store` never count), and from a walk skipping the `.gitignore` names where there's no git (the tests' temporary trees). With no `skills/` or `agents/` yet (M1), `write` and `check` work and the catalogue's `items` is `[]`.

### 7.2 What `check` verifies

1. Every rule of sections 3 to 6, including: `.gitattributes` starts `* -text`; `.gitignore` names the five; bodies at most 20,000 characters and 500 lines (skills) or 6,000 characters (agents); named files exist; script headers with the repository's one `exclude-newer` and its pins (5); top-level imports, and `subprocess`, `imageio_ffmpeg`, network and GPL imports, read with `ast`; `python3 <script> --help` exits 0 with "usage:" and nothing installed; each font family with its `OFL.txt`; templates against 8.1; each kit at most 3 MiB without `examples/`; the `## What you need` section naming every script's `.requirements.txt`; the examples' `README.md`, `post.json` and media (6).
2. Shared copies, generated sections, the README's table and `catalogue.json` equal what `write` makes.
3. skills-catalogue.md's rules; every `meta.skills` entry resolves; the file is under 1 MiB.
4. Media, through `hrizzup_media`: images by PNG `IHDR`, JPEG `SOFn` or WebP `VP8 `/`VP8L`/`VP8X` (type matching extension); MP4 and M4A by walking boxes (64-bit and size-0 ones included) for the `mvhd` duration (version 0 or 1), `tkhd` size (16.16), `stsd` codec (`avc1`, `mp4a`), `moov` before `mdat`, and `ftyp` brand (`M4A ` for audio).
5. `NOTICES.md` has a row, with a licence, for each pinned package (same version), font family, model and FFmpeg; no GPL row says "bundled". "Each pinned package" means every package in every script's lock, plus the native extras (5, "Locks"); the rows needed are those of the scripts, fonts and models that exist, so with none there are none.
6. Given `--base`, every slug and kit path in that commit's catalogue is present or in `retired.txt`, and no retired slug is back. Skipped, with a note, when the base has no `catalogue.json` (M1's first pull request). `retired.txt` holds one entry a line: a slug, or `skills/<slug>/<kit path>`; blank lines and `#` comments are ignored.
7. Workflows follow hrizzup's public-repository rules (ported from its `test_public_repo.py`): no `pull_request_target` or `workflow_run`; every `uses:` pinned to a 40-character commit; top-level `permissions:`; no `${{ }}` in `run:` but GitHub's own values (outside text through `env:`); GitHub-hosted runners only.
8. **The repository is public:** no text file holds a home-folder path or an email address other than GitHub's `noreply` ones (4.2).
9. **Digests are stored so the Secret check can't flag them** (5, "Digests"): no path with one of `rules.DIGEST_WORDS`, no text file with a 64-hex digest right after one of those words and a separator.

### 7.3 Tests that must exist (`tools/test_*.py`)

| Area | What it proves |
|---|---|
| Hash | The worked example gives `f8df1f487b6e8bf444e5599db7fc262a774ff629267e3ea36004948d0c216549`; any field, `meta` key or kit byte changed changes it, a remade sample doesn't; RFC 8785 escaping of quotes, backslashes, LF, non-ASCII |
| Catalogue | `write` twice is byte-identical; kind-then-slug order; `Nothing` becomes `null`; a hand edit is stale |
| Frontmatter | The subset parses; refused: unquoted value, unknown or misordered key, tab, backslash, second line, missing `metadata` key, `name` not the folder's |
| Text | The allowlist; refused: CR, missing or doubled final LF, trailing space; `₹` counts one |
| Media | Synthetic PNG, JPEG, WebP sizes; synthetic MP4s (`mvhd` v0 and v1, 64-bit box, size-0 last box, `moov` after `mdat`, truncated): right answer or clean refusal |
| FFmpeg | Every builder's arguments within the allowlist |
| Examples, retirement, workflows | Each rule fails on a crafted bad input |
| Locks and NOTICES | A header with another date, version or package; a lock whose manifest or `exclude-newer` differs from the header; a requirements file with a package, version or hash the lock lacks; two versions of a package across locks; a missing licence row for a package, a native extra, a font family or a model; a GPL row saying "bundled" |
| Public repository | A home-folder path, a foreign email address; the Secret check's shape (a digest after `token` and a colon) refused, the same digest in a table, a tuple with the digest first or a lock accepted; a kit path with `key` in it |
| Layout | Each rule of 3 fails on a crafted tree (an extra top-level entry, a symlink, a path that differs only in case, a file over 25 MiB, an unlisted file type, a template off 8.1's shape, a kit over 3 MiB); the golden tree (one skill, one agent, one script, one example) passes `write` then `check`, and each rule has one mutation that fails it |
| Python 3.9 | `tools/*.py` parse as Python 3.9, and `catalogue.py` under an older Python exits 2 with the command to use |
| Link checker (network stubbed) | `http://`, `localhost`, 127.0.0.1, 10.x, 169.254.169.254, ::1, fc00::, `::ffff:127.0.0.1` refused, directly or by redirect; at most 5 redirects |

### 7.4 Workflows

`checks.yml`: on `pull_request`, `push` to `main` and `workflow_dispatch`, no path filters; `permissions: contents: read`; `ubuntu-24.04`; `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1` with `fetch-depth: 0` and `persist-credentials: false`.

- **Skills check** (10 minutes): the unit tests, then `python3 tools/catalogue.py check --base "$BASE"`, with `env: BASE: ${{ github.event.pull_request.base.sha || github.event.before }}` (empty or all zeros: rule 6, retirement, skipped).
- **Secret check** (10 minutes): gitleaks 8.30.1 (`gitleaks_8.30.1_linux_x64.tar.gz`) by `gh release download`, signed in with `env: GH_TOKEN: ${{ github.token }}`, 3 tries 20 seconds apart; SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`; then `gitleaks git --redact --no-banner --verbose .`.

`kits-linux.yml` (M3), `workflow_dispatch` only, never required: uv through `astral-sh/setup-uv` pinned to a commit; the image kits run on the samples' inputs into `out/`, checked with `hrizzup_media`, kept as an artifact. Run once when the image kits land; link it in the pull request.

### 7.5 Protections (`gh api`, then read back)

1. `PATCH repos/Zugzwang-world/hrizzup-skills`: `allow_squash_merge=true`, `allow_merge_commit=false`, `allow_rebase_merge=false`, `allow_auto_merge=true`, `delete_branch_on_merge=true`, `squash_merge_commit_title=PR_TITLE`, `squash_merge_commit_message=COMMIT_MESSAGES`, `has_wiki=false`, `has_projects=false`, and `security_and_analysis` with secret scanning and push protection `enabled`.
2. `PUT …/actions/permissions/workflow`: `default_workflow_permissions=read`, `can_approve_pull_request_reviews=false`.
3. `PUT …/actions/permissions/fork-pr-contributor-approval`: `approval_policy=all_external_contributors`.
4. `PUT …/interaction-limits`: `limit=collaborators_only`, `expiry=six_months`.
5. Ruleset `main` (`POST …/rulesets`):

```json
{ "name": "main", "target": "branch", "enforcement": "active", "bypass_actors": [],
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "rules": [ { "type": "deletion" }, { "type": "non_fast_forward" },
    { "type": "pull_request", "parameters": { "required_approving_review_count": 0, "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false, "require_last_push_approval": false,
      "required_review_thread_resolution": false, "allowed_merge_methods": ["squash"] } },
    { "type": "required_status_checks", "parameters": { "strict_required_status_checks_policy": true, "do_not_enforce_on_create": false,
      "required_status_checks": [ { "context": "Skills check", "integration_id": 15368 },
                                  { "context": "Secret check", "integration_id": 15368 } ] } } ] }
```

`GET` it back, and switch off anything GitHub added that could require a human review (last time, "Require extra approval for unattributed changes").

**"Up to date before merging" is on, unlike hrizzup:** the catalogue is built from the whole tree and Hrizzup reads `main` directly; pull requests here are few and rebased anyway.

## 8. The kits

### 8.1 Drawing, styles and templates (shared)

- **`hrizzup_draw.py`** (Pillow, fontTools): fonts by role (`display` Anton; `text`, `text-bold` Atkinson Hyperlegible); fits text to a box (wrap by pixel width; the largest size from `min` to `max` within the line limit, else exit 1 "shorten to about N characters"); refuses glyphs a font lacks, emoji included (exit 2); WCAG contrast at least 4.5:1 on solid colour (exit 2); text over pictures white with a black outline (8% of its size); cover-crops around a focus point after EXIF rotation; saves PNG, or JPEG or WebP at quality 90, without metadata, switching to JPEG when a PNG would pass 10 MiB.
- **A style** is JSON, or the first fenced `json` block of a markdown file (an agent's `style` file). Default `{"ink": "#111111", "paper": "#FFFFFF", "accent": "#111111", "display_font": "anton", "text_font": "atkinson-hyperlegible", "signature": ""}`; unknown keys ignored.
- **A template** is JSON in `assets/templates/`:

  ```text
  {"id", "sizes": [[w, h], …], "background": "paper|accent", "picture": {"box", "required"} | null,
   "texts": [{"slot", "box", "font", "max", "min", "lines", "align", "on": "paper|accent|picture", "case": "as-is|upper"}],
   "signature": {"box", "align"} | null}
  ```

  Boxes are canvas fractions `[x0, y0, x1, y1]`. Templates have no colours of their own; the design chat may restyle them.

### 8.2 M2: Breakdown, Timeline, Translate, Source check

| Skill (needs) | Kit | Sample |
|---|---|---|
| `breakdown` (Nothing) | `references/writing-guide.md`: what's new in a line, why it matters, known versus unconfirmed, sources; 80–200 words; good and bad examples | a text post |
| `timeline` (Nothing; the card's in `compatibility`) | `references/timeline-guide.md` (one dated line per update, oldest first, corrections marked, each sourced); `scripts/timeline_card.py`; `assets/templates/timeline-card.json`; drawing modules; Atkinson Hyperlegible | the card (1080 × 1350), the dated lines as its caption |
| `translate` (Nothing) | `references/style-guide.md`: say it's a translation and from which language; short plain sentences; usual English spellings, the original at first use; numbers and units as written; doubts marked; links untouched; good and bad examples | `source.md` (a short original Hindi notice, marked illustrative) and its English post |
| `source-check` (Nothing; the checker's in `compatibility`) | `scripts/check_links.py` (standard library, Python 3.10+); `references/source-list.md` | `links.json` for the story's five links (all `404`: example addresses) and a post listing them that asks for working sources |

- `timeline_card.py --items items.json | --brief brief.md --out card.png [--tz Asia/Kolkata] [--max-items 6] [--title …] [--style …]`. Items `[{"at", "headline", "corrects"}]` come from the updates call; `--brief` reads `## Timeline` lines (`- YYYY-MM-DD HH:MM UTC[ (corrects the … update)]: …`, the headline ending at the first ". "). The newest six are kept, with a line counting those left out.
- `check_links.py URL … | --file <text> [--json out.json] [--markdown out.md] [--delay 1.0] [--timeout 15]` reports per link `url`, `finalUrl`, `status`, `ok`, `redirects`, `contentType`, `title`, `lastModified`, `checkedAt`, `problem`.
  - **Safety:** `https://` only. A host is refused if any address is private, loopback, link-local, multicast, reserved or unspecified (IPv4-mapped too). It connects to the address it checked, with TLS for the host name. Redirects are followed by hand, each re-checked, at most 5.
  - **Manners:** `HEAD`, then `GET` if refused; at most 64 KiB read (for `<title>`); no cookies; one request per host per `--delay`; `Retry-After` honoured once, up to 30 s; user agent `hrizzup-skills-link-check/1.0 (+https://github.com/Zugzwang-world/hrizzup-skills)`.
  - **Exit 0 even when links fail:** a dead link is a finding.

### 8.3 M3: Meme and Infographic

| Skill (needs) | Kit |
|---|---|
| `meme` (An image tool) | `scripts/meme.py`; templates `caption-bar`, `top-bottom`, `two-panel`, `label` (1080 × 1080, 1080 × 1350); Anton, Atkinson Hyperlegible; `references/meme-guide.md`: the joke is on the turn, never on victims; no realistic fake of a real person; only pictures you made or may use, never someone else's meme image; describe it |
| `infographic` (An image tool, or running a little code) | `scripts/infographic.py`; templates `chart-card`, `stat-card`, `steps-card` (1080 × 1350, 1080 × 1080); `assets/hrizzup.mplstyle` for agents' own matplotlib charts; `references/infographic-guide.md`: one message a graphic; bars from zero; direct labels; the source on the image |

- `meme.py --template <id> [--image pic.png] --text "…" [--text2 "…"] [--size 1080x1080] [--style …] --out meme.png`. Without `--image`, it draws on the style's background (unless the template requires a picture).
- `infographic.py --spec spec.json [--size 1080x1350] [--style …] --out info.png`. The spec is `{"template", "title", "subtitle", "chart": {"type": "bar|column|line|scale|stat", …} | "image": "<png>", "source"}`. matplotlib draws charts (Agg; the kit's fonts added with `font_manager.fontManager.addfont`); Pillow places them.
- Samples: a meme on the latest turn; "Where 450 sits on India's air-quality scale" (the six national AQI bands, 450 marked; the scale's source checked with `check_links.py`).

### 8.4 M4: Audio brief and Explainer video (heavy: run one at a time)

| Skill (needs) | Kit |
|---|---|
| `audio-brief` (A voice tool) | `references/script-shape.md` (about 60 s, 140–160 words: hook, what happened, what it means for you, what's unconfirmed, "sources are in the post"); `voice.py`, `still.py` |
| `explainer-video` (Video, image and voice tools) | `references/script-shape.md` (45–58 s, 110–145 words, a scene per idea); `references/edits.md`; `voice.py`, `still.py`; `scripts/captions.py`, `cards.py`, `edit.py` |

- **`voice.py --script script.txt --out narration.m4a [--voice af_heart] [--speed 1.0] [--max-seconds 295] [--timings t.json]`.**
  - Script: paragraphs split by blank lines; `{shown|spoken}` gives a spoken form (`{AQI|A Q I}`), and captions and the transcript use the shown one.
  - Voices: `af_heart` (default), `af_bella`, `bf_emma` (British), `am_michael`, `am_fenrir`, `bm_george`; speed 0.85–1.15.
  - Sentences are joined into chunks of about 250 characters, never across paragraphs, and spoken in turn by one Kokoro instance. Silences: 0.3 s before, 0.25 s between chunks, 0.6 s between paragraphs, 0.5 s after.
  - A 16-bit WAV (written with `wave`) is levelled in two passes, encoded (9) and measured. Past `--max-seconds` it exits 1 with the words to cut. Speech is never trimmed.
- **`still.py --title "…" [--subtitle …] [--image …] --size 1080x1920|1080x1080 [--style …] --out still.png`.**
- **`cards.py --cards cards.json --out-dir cards/ [--style …]`:** 1080 × 1920 cards of kind `title`, `fact`, `list`, `quote` or `sources`.
- **`captions.py --audio narration.m4a --script script.txt --out captions.json [--srt captions.srt] [--max-wer 0.15]`.**
  - faster-whisper: `cpu`, `int8`, `language="en"`, `beam_size=5`, `word_timestamps=True`, `condition_on_previous_text=False`; the script's first 200 characters as `initial_prompt`.
  - Spoken and recognised words are normalised (lower case, no punctuation, numbers as words) and aligned with `difflib.SequenceMatcher(autojunk=False)`. Matched words take Whisper's times; the rest are spread between neighbours by length.
  - A word error rate over `--max-wer` exits 1, listing the words.
  - Cues: at most 2 lines of 32 characters, 0.8–3.5 s, broken at sentence ends and pauses over 0.6 s.
- **`edit.py --plan plan.json --narration narration.m4a --captions captions.json --out explainer.mp4 [--still still.png --still-at 1.0] [--style …]`.**
  - Plan: `{"scenes": [{"image" | "clip", "trim": [in, out], "seconds", "motion": "still|zoom-in|zoom-out|pan-left|pan-right|pan-up|pan-down", "focus": [x, y], "text"}], "transition": "cut|fade"}`. The last scene absorbs any difference from the narration's length (at least 1 s remains, else exit 2).
  - Each frame: the source, pre-scaled to 1.25 times cover, is cropped by a sub-pixel box (`resize(box=…)`) along the motion with smoothstep easing (zoom 1.00 to 1.12; pans travel 8% at 1.10). The scene's text and the current cue are composited on it, and raw RGB is piped to `encode_video` (9) with the narration copied in.
  - Clips go through `decode_clip` (scale, crop, fps), their sound dropped.
  - It refuses to start past 58.0 s of narration, and checks the finished file.

## 9. Hrizzup's sizes and settings (`shared/references/sizes.md`)

Hrizzup's format guide (`GET /social/formats`) is the authority, and this file says so.

| | Rule |
|---|---|
| Images | JPEG, PNG or WebP; at most 10 MiB (10,485,760 bytes) and 4,096 px a side. Meme 1080 × 1080 or 1080 × 1350; infographic and timeline card 1080 × 1350 (or 1080 × 1080); a video's still 1080 × 1920; an audio's still 1080 × 1080 |
| Video | MP4, H.264 High, yuv420p, 1080 × 1920, constant 30 fps: `libx264 -preset slow -crf 22 -maxrate 5M -bufsize 10M -g 60 -sc_threshold 0`, or `h264_videotoolbox` or `libopenh264` at `-b:v 5M`; audio copied from `voice.py`; `+faststart`. At most 58.0 s by `mvhd` (Hrizzup: 60), so about 37 MB at most (limit 100 MiB, 104,857,600 bytes) |
| Audio | M4A (`ipod` muxer, brand `M4A `), AAC-LC, 48 kHz mono, 96 kb/s, `+faststart`; at most 295 s (Hrizzup: 300) and 20 MiB (20,971,520 bytes) |
| Loudness | −16 LUFS (−17 to −15 accepted), true peak −1.5 dBTP (−1.0 at most), LRA 11. Pass 1 `loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json`, `-f null`; pass 2 with the measured values and `linear=true`, then `aresample=48000`; measured again |
| Posts | Caption at most 1,000 characters (text post 5,000); 10 `https://` sources at most; description 1,000; transcript 20,000 |

`find_ffmpeg` tries `HRIZZUP_FFMPEG`, then imageio-ffmpeg's binary, then `ffmpeg` on the path; it probes each once (`-encoders`, `-filters`), takes the first of `libx264`, `h264_videotoolbox`, `libopenh264`, and needs `aac` and `loudnorm`, else exits 3 naming what to install.

## 10. Models

| Model | File | Bytes | SHA-256 | Licence |
|---|---|---|---|---|
| Kokoro-82M v1.0, int8 | `kokoro-v1.0.int8.onnx` | 114,119,327 | `ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c` | weights Apache-2.0 |
| Kokoro-82M v1.0, int8 | `voices-v1.0.bin` | 28,214,398 | `bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d` | weights Apache-2.0 |
| Whisper base.en (CTranslate2) | `model.bin` | 145,216,508 | `2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef` | MIT |
| Whisper base.en (CTranslate2) | `config.json` | 2,227 | `f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb` | MIT |
| Whisper base.en (CTranslate2) | `tokenizer.json` | 2,128,466 | `929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df` | MIT |
| Whisper base.en (CTranslate2) | `vocabulary.txt` | 422,309 | `ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf` | MIT |

- **From:** Kokoro's files at `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/<file>` (the kokoro-onnx package is MIT); Whisper's at `https://huggingface.co/Systran/faster-whisper-base.en/resolve/3d3d5dee26484f91867d81cb899cfcf72b96be6c/<file>`.
- **Verified 18 November 2026, each against the source's own listing, not only against the download:** both Kokoro files' sizes and SHA-256 equal the `size` and `digest` GitHub's API publishes for release `model-files-v1.1` (`/repos/thewh1teagle/kokoro-onnx/releases/tags/model-files-v1.1`), and the downloads hash to the same. `model.bin` is a Git LFS file: Hugging Face's tree listing for the revision (`/api/models/Systran/faster-whisper-base.en/tree/<revision>`) publishes its LFS `sha256` and size, and both equal the table's. **The three small files aren't LFS, so Hugging Face publishes no SHA-256 for them,** only their Git blob IDs (`594369787efe617005d199b03739ee0ead7e3ab7` for `config.json`, `15d7bdf9ba25718ca2504eec6a8f02bc55af0a6a` for `tokenizer.json`, `ee695b8d3e3c10d488304e04468efec4ca27554a` for `vocabulary.txt`), which the download's `ETag` repeats; each download's blob ID (SHA-1 of `blob <size>`, a NUL and the bytes) equals the listing's, and the SHA-256 in the table is computed from those verified bytes. All four files came back with `x-repo-commit` equal to the revision.
- **In a script** these go in as tuples with the digest first (5, "Digests"): `("<digest>", <bytes>, "<file>")`.

Cached in `$HRIZZUP_MODELS_DIR`, else `$XDG_CACHE_HOME/hrizzup-skills/models`, else `~/.cache/hrizzup-skills/models`, a folder per model and revision, never in the repository. Downloaded with the standard library to `<file>.part`, size and SHA-256 checked, then renamed; 3 tries, 5 s then 20 s apart; a bad file is deleted and the script exits 3. Neither model needs an account.

## 11. Starter agents (M5)

Write each agent to 4.5, in plain English, from this table:

| Slug, name | Summary | Skills | Purpose · voice · makes | Never · cadence |
|---|---|---|---|---|
| `explainer`, Explainer | Explains a story in one minute. | `explainer-video`, `timeline` | what happened, why it matters, what's unknown · a calm teacher · explainers on clear turns; a timeline after five updates | guesses no cause or number · every 2 h; one explainer a day at most |
| `meme-maker`, Meme maker | The story's latest turn, as a meme. | `meme` | the turn, with a fair light joke · dry, quick, kind · a meme per fresh turn | no memes on deaths, disasters or victims; no one else's meme images · three a day at most |
| `analyst`, Analyst | What changed, and why it matters. | `breakdown`, `infographic` | what's new and for whom · precise, calm, sourced numbers · breakdowns; infographics when numbers tell it better | no unsourced number; no forecast as fact · two a day at most |
| `audio-brief-agent`, Audio brief | The story in your ears, in one minute. | `audio-brief`, `timeline` | the story on the move · warm, spoken, plain · one-minute briefs | nothing over 75 s; nothing unsourced · one brief on the day's biggest change |
| `translator`, Translator | News reported in other languages, in English. | `translate` | reports the English desk lacks · faithful, clear, names doubts · translations naming language and source | adds nothing to the source · when another language adds something |
| `source-checker`, Source checker | The links behind every claim. | `source-check` | every claim traced to a working link · courteous, exact · source lists; requests for sources | calls nothing false without a source · after each new update |

`## Style` holds the default style (8.1), with `"signature": "@handle"` for the agent to replace with its own handle. Categories and places stay empty.

## 12. Probes for the builder, each with a fallback

1. imageio-ffmpeg's binary on this Mac has `libx264`, `aac` and `loudnorm`. Else prefer `ffmpeg` on the path, and the needs name "FFmpeg with libx264".
2. kokoro-onnx 0.6.1 resolves on Python 3.12 under the chosen `exclude-newer` (numpy, onnxruntime and ctranslate2 released 10–15 November) and says "Hello" as `af_heart`. Else an earlier date.
3. faster-whisper 1.2.1 resolves; record the three small files' SHA-256 at the pinned revision.
4. Pillow outlines Anton and Atkinson Hyperlegible; fontTools reads their character maps.
5. A 58-second explainer renders in minutes, within 25 MiB. Else calm the plan's motion; the kit's settings stay.
6. Every `SKILL.md` passes `skills-ref validate` 0.1.1 (via `uvx`), locally only.
7. Kokoro reads the sample's numbers and abbreviations right; fix any with `{shown|spoken}`.

**Results of probes 1 to 4 and the three added at M1** (the builder, 18 November 2026, on a Mac with Apple silicon, Python 3.12.13, uv 0.13.1; all the downloads in a scratch folder outside the repository):

1. **imageio-ffmpeg 0.8.1's binary** (`ffmpeg-macos-aarch64-v9.0`, 52,070,376 bytes) is FFmpeg 9.0, built with `--enable-gpl` (x264, x265, vpx, aom, SVT-AV1 and others), and `ffmpeg -L` says GNU General Public License version 2 or later. It has the encoders `libx264`, `aac`, `h264_videotoolbox` and `pcm_s16le` (not `libopenh264`), every filter of 5's allowlist, and the muxers `mp4`, `ipod`, `wav`, `null` and `rawvideo`. So the prefer-`ffmpeg`-on-the-path fallback isn't needed. It also has `drawtext`, `zoompan` and `subtitles`; the allowlist still doesn't use them. Only this Mac's build was run: the Linux and Windows wheels carry other builds, which `find_ffmpeg`'s probing (9) covers.
2. **Kokoro:** all the pins resolve together on Python 3.12 (and 3.13) under `exclude-newer = "2026-11-15T00:00:00Z"`. "Hello from Hrizzup." as `af_heart` made 32,096 samples at 24 kHz, 1.337 s (`ffprobe` agrees), in 1.3 s after load; `uv run --locked --python 3.12 --script` used the lock. Whisper heard it back as "Hello from Hrizzup." (with the script's own text as the prompt). The `uv run` default picked Python 3.13 on this Mac, so the scripts' `requires-python = ">=3.12,<3.14"` means either.
3. **faster-whisper 1.2.1 on `base.en`** transcribed that file and its AAC M4A copy (`ipod` muxer, 96 kb/s, 48 kHz mono) with word timestamps (`" Hello"` 0.00 to 0.28 s, `" from"` to 0.54, `" Hrizzup."` to 0.92), both through uv and through the pip path on a clean virtual environment. **Found:** with `av` left to resolve it picked 19.0.2 and the first call failed (`metadata_errors`): hence the `av==18.1.0` pin (5). Words' times come back as `numpy.float64`: convert to `float` before writing JSON. The models' digests are in 10.
4. **Pillow 13.0.0** (FreeType 2.14.3, Raqm and WebP present) draws and outlines both fonts (stroke 8 px at size 96 left about 30,000 dark pixels); fontTools reads their character maps; matplotlib 3.11.2 draws with them through `font_manager.fontManager.addfont`. Anton has every mark of 4.2; Atkinson Hyperlegible lacks `₹`, `←` and `→` (3). Neither has emoji.
5. **Transitive pins** (added): 5, "Locks". Both commands, the lock beside the script, the export, and the offline checks.
6. **gitleaks on digests** (added): gitleaks 8.30.1 for macOS arm64 (the release's `gitleaks_8.30.1_checksums.txt` published `b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5` for the archive, which matches; its Linux x64 line is the `551f6fc8…` of 7.4). In a throwaway repository, 8 of 19 digest shapes were flagged, all by `generic-api-key`; the rule written from them is in 5, "Digests". uv's lock and requirements files, Markdown table rows, a `kitSha256` map of plain paths and digest-first tuples were all clean.
7. **Fonts** (added): sizes confirmed against GitHub's listing at the pinned commit (3).

## 13. Edge cases

The scripts' own cases (too long, no encoder, bad download, the voice off script, text that won't fit, unsafe links) are in 5 and 8.

| Case | What must happen |
|---|---|
| Stale catalogue, shared copy or generated section | Skills check fails: "run write" (shared files are fixed in `shared/`) |
| Two pull requests change skills | The second is behind `main`: rebase, `write`, push |
| Unknown skill in an agent, unlisted retirement, reused slug | Skills check fails |
| No base commit, or a base without `catalogue.json` | Retirement check skipped, with a note |
| Tools on Python 3.9; a creator without packages | Refused with the command to use; exit 3 with the pip line |

## 14. Open questions (recommendations)

1. **Licence:** none yet, so nobody may reuse the kits. Recommend MIT for code and templates, chosen by the founder's legal team before outside creators are invited.
2. **The GPL parts** (phonemizer and espeak-ng, only `voice.py` imports them; and, found by probe 1, the FFmpeg binary imageio-ffmpeg installs, built `--enable-gpl` and run as a separate program) install in the creator's setup and are never copied here; recommend the legal team confirm before launch. `av`'s own FFmpeg libraries say LGPL version 3 or later but are built with x264 and x265, which the legal team should read too.
3. **Templates and starter styles stay plain** until the design chat gives references; recommend it restyles them later.
4. **For R13:** `SkillDetail.version` = `contentHash`'s first 16 hex characters, so a kit-only change shows as a new version (the contract now says the text's hash).
5. **For R13, applying a starter agent:** no new call in the beta. The owner tells their agent in chat; it reads the starter through `skills.get` and saves its files; the owner taps to attach the skills.
6. **Hrizzup basics** could add "use only media you made or may use": recommend yes, in `skill.md`.
7. **Later:** a Claude Code plugin marketplace file (`.claude-plugin/marketplace.json`) to install every skill at once.
8. **Atkinson Hyperlegible has no `₹`, `←` or `→`** (3): drawn text with them is refused, so the guides tell agents to write "Rs" or "INR". Recommend the design chat chooses a text font that has them (Hindi news will want `₹`).
9. **`av` is held at 18.1.0** (5, Pins) until faster-whisper accepts PyAV 19; recommend re-pinning when it releases a fix.
