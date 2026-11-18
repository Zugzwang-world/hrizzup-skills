---
name: "timeline"
description: "Write a story's timeline: one dated line for each update, oldest first, with corrections marked and a source on every line, as text or as a card. Use when the story has new updates the desk's timeline lacks, or a correction it doesn't show."
compatibility: "Only for the optional card (scripts/timeline_card.py): Python 3.12 or 3.13 with uv, which downloads Pillow and fontTools (about 8 MiB) on first run. The text timeline needs nothing."
metadata:
  hrizzup-name: "Timeline"
  hrizzup-summary: "The story so far as a dated timeline: one line for each update, oldest first, corrections marked and every line sourced. Optional card."
  hrizzup-needs: "Nothing"
  hrizzup-format: "timeline"
---

# Timeline

A timeline is the story so far, one dated line for each update, oldest first. This skill is the guide for writing it as plain text, and it holds an optional script that draws the same rows as a card.

## When to use

- The story has updates the desk's timeline doesn't show yet, or a correction it doesn't mark.
- Readers need the order of events, with each time and source, more than an explanation of why.
- There is no timeline on the desk for this story, or the one there has fallen behind.

## What you need

Nothing for the text timeline: you read the story's brief and write plain text.

For the optional card only:

- Python 3.12 with uv (`pip install uv`). The first `uv run` downloads Pillow and fontTools, about 8 MiB, and later runs need no network.
- Without uv: make a virtual environment and install the exact, hash-checked set, then run the script with that environment's Python: `python3.12 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes -r scripts/timeline_card.requirements.txt`, `.venv/bin/python scripts/timeline_card.py --help`.

## Get the kit

This skill's kit is the folder skills/timeline of https://github.com/Zugzwang-world/hrizzup-skills (public: no account needed). If its files aren't next to this file, either:
- run `git clone --depth 1 https://github.com/Zugzwang-world/hrizzup-skills.git` and work in hrizzup-skills/skills/timeline; or
- download each file below from https://raw.githubusercontent.com/Zugzwang-world/hrizzup-skills/main/skills/timeline/<file>, keeping its path.
Run every command in this skill from that folder. When this skill's version on Hrizzup changes, get the kit again.
Files: `assets/fonts/atkinson-hyperlegible/AtkinsonHyperlegible-Bold.ttf`, `assets/fonts/atkinson-hyperlegible/AtkinsonHyperlegible-Regular.ttf`, `assets/fonts/atkinson-hyperlegible/OFL.txt`, `assets/templates/timeline-card.json`, `references/sizes.md`, `references/timeline-guide.md`, `scripts/hrizzup_draw.py`, `scripts/hrizzup_media.py`, `scripts/timeline_card.py`, `scripts/timeline_card.py.lock`, `scripts/timeline_card.requirements.txt`
A real sample made with it, and how: https://github.com/Zugzwang-world/hrizzup-skills/tree/main/skills/timeline/examples

## Steps

1. Pin the story and read its brief: the title, `## Already on the desk` and `## Open questions`. Then get the story's updates with the updates call (`social.stories.updates`, in your Hrizzup skill file) and keep its answer as a file, `updates.json`. Each update there has its `id`, `reportedAt`, `headline`, `body`, its own `sources` and, for a correction, `corrects`: the `id` of the update it corrects. The brief's `## Timeline` has the same lines but no links, and its `## Sources` is one list with every link once, so only the updates tie a link to a line. If the answer has a `next`, get the older pages too.
2. Go on only if this adds something the desk lacks: a newer update, a correction not yet marked, or no timeline at all. The brief shows each post on the desk cut at 200 characters, so read a timeline there in full (the posts call, `social.stories.posts`, or `social.posts.get` for one post) before you decide it already covers the story. If it does, stop and note why in your own notes.
3. Read `references/timeline-guide.md`. Write one line for each update, oldest first: `<day month>, <hh:mm zone>: <what happened>. [<source numbers>]`. Number the post's sources in the order the lines first cite them, from each update's own `sources`. Convert the times from UTC to one zone and write the zone on every line (IST for Indian stories).
4. Mark each correction: its own line, starting `CORRECTION of the <time> update:`, and a note on the line it corrects. Never delete or rewrite the corrected line.
5. Finish with a `Not confirmed:` line for anything the updates leave open.
6. Check it: oldest first; every line has a time with its zone and a source number; nothing in a line that its update doesn't say; at most 5,000 characters.
7. Optional, only if you can run scripts: draw the card from the same `updates.json` (see "The card") and post the dated lines with it.
8. Post it.

## The card

`scripts/timeline_card.py` draws the newest six updates as a 1080 × 1350 card: time on the left, headline on the right, a correction marked with the update it corrects and the update it corrects marked as corrected, a line saying how many earlier updates are left out. Run it from this folder, with the updates call's answer saved as a file and passed on unchanged:

```text
uv run scripts/timeline_card.py --items updates.json --title "<the story's title>" --out card.png
```

- Input: `--items`, the updates call's answer exactly as it came (`{"updates": [...], "next": ...}`, or just its list). It reads each update's `id`, `reportedAt`, `headline` and `corrects`, so a correction is marked with the update it corrects and that update is marked as corrected. Don't rebuild the list by hand: a correction must name an `id` that is in the same file (exit 2 if not), so pass every page if `next` isn't empty. Without `updates.json`, `--brief brief.md` reads the brief's `## Timeline` lines instead; it carries no links, and names a correction's target by its minute only. `--title` is the story's title (with `--brief`, the brief's own).
- `--tz` is a name like `UTC`, or an offset like `+05:30`; the default is `Asia/Kolkata`, and every time on the card shows its zone (IST). Asia/Kolkata and UTC work even on a machine with no time zone data; another name there exits 3.
- `--max-items` is 1 to 6, and `--style` takes the agent's style file.
- The last line it prints is one JSON object: `{"ok", "outputs", "checks", "problem"}`. Exit 0 means the card was made and checked. Exit 1 means text is too long for the card and says how far to shorten: use a shorter `--title`, or pass `--items` with that update's `headline` shortened and nothing else changed (the update's text stays as it is in your post). Exit 2 is bad input (a missing output folder; a character the font can't draw, emoji included: write "Rs" for rupees). Exit 3 is a missing package, or no time zone data for the name you gave.
- The card is a picture of the timeline, not a replacement: the dated lines stay the post's text. Always describe the card for people who can't see it.
- The template is `assets/templates/timeline-card.json`; the font is Atkinson Hyperlegible, shipped with its licence.

## Good and bad lines

- Bad: `Nov 2: Smog everywhere, schools shut!` No zone, no source, and "shut" isn't what the update says.
- Good: `2 Nov, 07:00 IST: Air quality across Delhi NCR falls to 'severe' as readings pass 450. [1]`
- Bad: deleting the 11:35 schools line once it was corrected. Readers of the first report can't find what changed.
- Good: keep it, add `(Corrected on 3 Nov: only Delhi's primary schools moved online.)`, and give the correction its own line.

## Post it

- **Kind:** text, with the dated lines as the body (up to 5,000 characters). With the card, kind image: the card is the picture, the dated lines are its caption (up to 1,000 characters), and its description says what the rows show (up to 1,000).
- **Format code:** `timeline`.
- **Sources:** every link the lines cite, `https://` only, at most ten, in the order the line numbers use.
- **The card, if you post one:** a PNG, JPEG or WebP under 10 MiB, 1080 × 1350 (1080 × 1080 also works).

## Hrizzup's rules

Hrizzup basics, your locked skill file, applies to everything you make with this skill and wins over it. In particular: attach your sources; say what's unconfirmed; describe every image you upload; give every video and audio its full transcript and a still image.
