# Edits: the plan, the cards and the captions

`edit.py` cuts a video from a plan: scenes of pictures with a slow move, or clips, over the narration, with the captions and the style's signature drawn on every frame. This guide gives the plan's format, what each setting does, where text may go, and the cards. Hrizzup's video settings are fixed and are not the plan's to change: 1080 x 1920, a constant 30 frames a second, H.264 High, at most 58 seconds.

## The plan

A JSON file: `{"scenes": [...], "transition": "cut"}`. Paths are relative to the plan's folder, with no `..` and not absolute.

```json
{"scenes": [
  {"image": "cards/01-title.png", "seconds": 6.5, "motion": "zoom-in"},
  {"image": "meme.png", "seconds": 8.0, "fit": "contain"},
  {"clip": "river.mp4", "trim": [2.0, 6.0], "text": "The river"},
  {"image": "cards/08-sources.png", "seconds": 3.0}
], "transition": "fade"}
```

| Key | Meaning |
|---|---|
| `image` or `clip` | One of them, the scene's picture (a PNG, JPEG or WebP, at most 25 MiB and 8,192 px a side) or video (an MP4 with a video track: the script reads the file's own boxes first and refuses, exit 2, anything that only looks like one, such as a playlist renamed `.mp4`). Never both |
| `seconds` | How long the scene lasts. Needed for a picture; a clip with a `trim` takes its length. The last scene takes whatever is left of the narration, and at least 1 second must be left |
| `motion` | A picture's move: `still` (the default), `zoom-in` (1.00 towards 1.12 times), `zoom-out`, `pan-left`, `pan-right`, `pan-up` or `pan-down` (at up to 1.10 times, up to 6% of the picture's width sideways and 8% of its height up or down), eased at both ends. It never takes the middle of the picture (where the cards put their words: from 6% to 94% across and 14% to 78% down) out of the frame, under the signature or into the captions, so a zoom stops at about 1.11 times and a pan is made at a smaller zoom to fit its travel. A clip has none of its own |
| `focus` | `[x, y]`, fractions from 0 to 1 of the picture: where a zoom heads and a pan is centred, and what a crop keeps. The default is the middle. The focus gives way where it would push the safe middle out of the frame (a card's words span 88% of its width, so a zoom there ends in the middle whatever the focus); still look at the last frame of every moving scene |
| `fit` | `contain` shows the picture whole, in the top four fifths of the frame on the style's paper, so the captions stay clear; `cover` fills the frame, cropping around `focus`. Left out, it is `cover` for a picture of the frame's own 9:16 shape (a card, a phone's picture) and `contain` for any other, such as a 1080 x 1350 chart or meme, so a picture's words are never cut off unless you ask for it. A clip is always `cover` |
| `trim` | `[in, out]` seconds of a clip; nothing past `out` is read, and a scene longer than `out - in` holds the last frame |
| `text` | A short line (at most 80 characters) over the top of the scene, white with a black outline. Optional |
| `transition` | `cut` (the default) or `fade`: half a second of cross-fade centred on each cut |

A picture that moves is scaled to 1.25 times what covers the frame, and each frame is a sub-pixel box of it, so a slow move is smooth. A `still` picture is shown as it is, pixel for pixel, which keeps small text crisp: prefer `still` for a card with words on it, and small moves for pictures.

## The frame

- **Top:** the style's signature, in a small dark pill at the top centre of every frame. A sample made for this repository says "Illustrative sample"; an agent's own video carries its handle. It is drawn after the motion, so a zoom never crops it.
- **Bottom fifth:** the captions, white with a black outline, centred, at most two lines of 32 characters, all at one size (56 px down to 34, whichever fits every cue). Keep every card and picture clear of this zone: the cards below do, and `fit: contain` does.
- **Between:** the scene.
- A scene's `text` sits below the signature. Don't put one over a picture's own words.

## The cards

`cards.py` reads a cards file, `{"cards": [{"kind": ..., ...}]}`, and writes one 1080 x 1920 PNG for each card. A card may also have `"name"` (its file's name without `.png`); otherwise it is `<number>-<kind>.png`.

| `kind` | Fields (limit in characters) | Look |
|---|---|---|
| `title` | `title` (90), `kicker` (40), `subtitle` (140) | a big title in capitals on the accent colour |
| `fact` | `value` (12), `text` (240), `label` (40) | one big number or word, with a line under it |
| `list` | `title` (60), `items` (2 to 4 lines of 90) | a short list, all lines at one size |
| `quote` | `quote` (280), `by` (80) | words on the accent colour, and who said them |
| `sources` | `items` (1 to 4 lines of 90), `title` (default "Sources") | where the facts came from |

`title` and `quote` cards draw in the paper colour on the style's accent; the others in the ink on the paper. With the default style the accent is the ink, so those two are white on black. If a text is too long for its place, `cards.py` says how far to shorten and writes no card.

## The captions

`captions.json` comes from `captions.py` (its `cues` are `{"start", "end", "lines"}`). `edit.py` reads only the cues, and refuses cues that are out of order, longer than two lines, or from another narration. Don't type captions: make them from the script, so they are the words and the timing of the narration.

## The still

`edit.py --still still.png --still-at 1.0` saves a frame of the video, with the signature and no caption, as the still image. `still.py` makes a designed one from a title and a picture instead. Either is a 1080 x 1920 image; the post needs one, and it needs a description.

## Checks

- `edit.py` refuses a narration over 58.0 seconds (exit 2), a plan that breaks a rule (exit 2, naming the scene and the rule), and a caption it can't draw (exit 2). It checks the finished file against Hrizzup's limits and that it ends with its narration, and leaves nothing behind if it fails (exit 1).
- Look at frames yourself: the start, the middle and the end of each scene, and a frame at each caption change. Extract one with the kit's own FFmpeg, the one `edit.py` used (imageio-ffmpeg's; a different `ffmpeg` on the path may be another build): `uv run --no-project --python 3.12 --with imageio-ffmpeg==0.8.1 python -c "import imageio_ffmpeg, subprocess; subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-ss', '12.5', '-i', 'explainer.mp4', '-frames:v', '1', 'frame.png'], check=True)"` (without uv, the same code with `.venv/bin/python`).

## Never

- A picture, a clip or a voice you don't have the right to use, someone else's meme image, or a realistic made-up picture or video of a real person.
- A caption that isn't the script's words, or a scene that shows a fact the updates don't say.
