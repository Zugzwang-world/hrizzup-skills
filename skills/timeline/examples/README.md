Illustrative: made from Hrizzup's example story, not real news; its sources are example addresses.

# Timeline: a sample

A timeline of Hrizzup's example story (Delhi NCR's smog and its schools): the dated lines as a text post, and the optional card beside them.

## Input

- `brief.md`: the story's brief, as Hrizzup builds it (the same text Hrizzup's own tests use for this story). Its `## Timeline` lists four updates, the last one a correction of the second.

## How it was made

The post was written by hand from `brief.md`, following `references/timeline-guide.md`: times converted from UTC to IST (01:30 UTC is 07:00 IST), the corrected line kept and marked, the correction on its own line, and one `Not confirmed:` line for what the updates leave open. Each line carries the numbers of its sources.

The card is the optional extra, made from the skill's folder with:

```text
uv run scripts/timeline_card.py --brief examples/brief.md --out examples/card.png --tz Asia/Kolkata
```

- Python 3.13.16 (the one uv chose; the script accepts 3.12 or 3.13), uv 0.13.1, Pillow 13.0.0, fontTools 4.68.0, Atkinson Hyperlegible (from the kit's `assets/fonts`). No FFmpeg and no models.
- Machine: a Mac with Apple silicon. Date: 18 November 2026.
- It printed one JSON line: `"ok": true`, both checks `true`. Run again from a clean copy of the repository, with uv (`uv run --locked`) and with the no-uv path (a virtual environment installed from `scripts/timeline_card.requirements.txt` with `--require-hashes`), it made the same file, byte for byte.

## Results

- `card.png`: a PNG, 1080 × 1350, 126,292 bytes (the repository's budget for a picture is 2 MiB), four rows with the second and fourth marked: the second, the claim that was corrected, says "Corrected 3 Nov, 09:20 IST", and the fourth, the correction, says "Corrects the 2 Nov, 11:35 IST update". Checked: `strings` on the file prints no home-folder path, and the file holds no metadata chunks, only the image's header, its data and its end.
- `post.json`: the post the sample would make (without its `requestId`): a text post, format `timeline`, 747 characters, with the story's five links as its sources, numbered the way the lines cite them. The card is not part of the post: this skill's default is text, and the card is an extra an agent may add as an image post with the same lines as its caption.

## Files

- `README.md`: this file.
- `brief.md`: the input.
- `post.json`: the post.
- `card.png`: the card.
