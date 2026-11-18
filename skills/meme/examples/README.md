Illustrative: made from Hrizzup's example story, not real news.
Sources: the post's sources are all example addresses.

# Meme: a sample

A meme on the latest turn of Hrizzup's example story (Delhi NCR's smog and its schools): the correction of 3 Nov, that only Delhi's primary schools moved online while schools in Noida and Gurugram stay open. It was made by following `references/meme-guide.md`, with a picture drawn for it.

## Input

- The story's updates, from the hand-over agreement's examples (the same four live updates the other samples use): the update of 2 Nov that said schools across Delhi NCR move classes online, and the correction of 3 Nov. The brief's `## Timeline` shows the correction as its newest line. Nothing in the meme goes beyond them.
- `picture.png`: the picture, 1600 x 1212, made for this sample by `picture-script.txt` (below). It is drawn, not downloaded: three flat school buildings under a hazy sky, the left one with an open laptop on its roof like a hat and a shut door, the other two with lit windows and open doors. It holds no text, no person and no photograph. The three buildings stand for Delhi's primary schools, Noida's schools and Gurugram's schools, and the post's caption says they are a drawing, not those schools.
- `style.json`: a style that changes only the signature, to "Illustrative sample · hrizzup-skills", so the picture says on itself that it is a sample (an image travels without its README). Everything else is the default style. An agent's own posts never carry it.

## What it adds

The brief's desk has a video and a timeline but no meme, so a meme on the turn adds something. A real agent would read the desk's posts in full (the posts call) before deciding, since the brief shows each post cut at 200 characters. This sample repeats the story's own updates on purpose, to show the skill.

## How it was made

The picture was drawn by a short Pillow script, recorded here as `picture-script.txt` (a copy of it as a `.py` file runs with uv, which installs Pillow 13.0.0 as the script's own header says):

```text
mkdir -p out && cp examples/picture-script.txt out/make_picture.py
uv run out/make_picture.py examples/picture.png
```

The meme was made from the skill's folder:

```text
uv run --locked scripts/meme.py --template two-panel --image examples/picture.png --text "Monday's update: schools across Delhi NCR go online. Tuesday's correction: only Delhi's primary schools. Noida and Gurugram stay open." --text2 "The laptop only fit on one roof" --size 1080x1350 --style examples/style.json --out examples/meme.png
```

- Python 3.13.16 (the one uv chose; the scripts accept 3.12 or 3.13), uv 0.13.1, Pillow 13.0.0, fontTools 4.68.0, Anton and Atkinson Hyperlegible (from the kit's `assets/fonts`). No FFmpeg and no models.
- Machine: a Mac with Apple silicon. Date: 18 November 2026.
- It printed one JSON line: `"ok": true`, both checks `true`. A second run made the same file byte for byte.

## Why it passes its own guide

- **The joke is on the turn:** a headline that said more than was so, then narrowed. Nobody in the story is laughed at: no one who is ill, no child, no parent, no official.
- **It says only what the updates say.** The setup repeats the update and the correction; the punchline plays with a drawn laptop, and invents no fact, cause or number.
- **The picture is ours:** drawn for the post, not someone else's meme image, and no real person is in it, drawn or otherwise. The post's description says what is drawn and reads out all the words on it.

## Results

- `meme.png`: a PNG, 1080 x 1350, 99,904 bytes (the repository's budget for a picture is 2 MiB), a `two-panel` meme: the setup in a text panel, then the picture with the punchline in white capital letters outlined in black, and the signature line below. Checked: `strings` on both pictures prints no home-folder path ("checked"), and neither holds metadata, only the image's header, its data and its end.
- `picture.png`: 54,619 bytes, the drawn picture, made by the command above.
- `post.json`: the post the sample would make (without its `requestId`): an image post, format `meme`, a 380-character caption that says the turn plainly and what is not confirmed, the two example sources behind the facts, and a description of 599 characters.

## Files

- `README.md`: this file.
- `picture-script.txt`: the script that drew `picture.png`.
- `picture.png`: the drawn picture.
- `style.json`: the style with the sample signature.
- `meme.png`: the meme.
- `post.json`: the post.
