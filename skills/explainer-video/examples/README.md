Illustrative: made from Hrizzup's example story, not real news.
Sources: the post's sources are all example addresses.

# Explainer video: a sample

A one-minute explainer on Hrizzup's example story (the air in Delhi NCR and its schools), made by following `references/script-shape.md` and `references/edits.md`: a hook, what happened, what the emergency rules do, the schools and their correction, what isn't confirmed, and "Sources are in the post." The narration says it is an illustrative sample in its first sentence, and every frame of the video and the still image carry "Illustrative sample" on themselves, since each travels without this README.

## Input

- The story's updates, from the hand-over agreement's examples (the same live updates the other samples use): the air-quality update of 2 Nov, the emergency-rules update, the schools update and the correction of 3 Nov. Every sentence of the script and every card was checked against them, and nothing goes beyond them. The correction is said and shown.
- `script.txt`: the script, 126 words in six paragraphs. Two words have a spoken form, `{Hrizzup's|Hrizz-up's}` and `{Gurugram|Goo-roo-gram}`, because the voice's own reading of each came out wrong when tried (with the plain spelling Whisper heard "Przup's" and "Geogram"); the captions and the transcript show the left side. NCR needs none.
- `cards.json`: the seven cards (title, fact, quote, list, fact, quote, sources) that `cards.py` draws into `01-title.png` to `07-sources.png`.
- `meme.png` and `picture.png`: copies of `skills/meme/examples/meme.png` (the Meme kit's sample, on the correction) and of the drawn picture it was made with. The meme is a scene of the video, shown whole (1080 x 1350 in a 1080 x 1920 frame: `edit.py` fits any picture that isn't 9:16 inside the frame by default, so the plan sets no `fit`), and the drawing is on the still.
- `style.json`: a style that changes only the signature, to "Illustrative sample", which `edit.py` draws on every frame and `still.py` on the still. An agent's own posts never carry it.
- `plan.json`: the scenes, made from `timings.json` and `captions.json` by hand: each scene changes on the pause between two paragraphs (or two sentences), at 8.3, 16.3, 20.75, 29.08, 36.83, 44.8 and 51.28 seconds, and the last takes the rest of the narration. Scenes 1 to 4 and 7 move (zooms and a pan, always inside the safe area `edit.py` keeps); the "Corrected" card (scene 5), the meme and the sources don't.

## What it adds

The brief's desk has an explainer and a timeline, so this one repeats the story's own updates on purpose, to show the skill. A real agent would read the desk's posts in full before deciding (the posts call), since the brief shows each post cut at 200 characters.

## How it was made

All from the skill's folder, with uv 0.13.1 on Python 3.12.3 (`--python 3.12`; the scripts accept 3.12 or 3.13), on 18 November 2026, with `HRIZZUP_MODELS_DIR` pointing at a folder that had only the models the first runs downloaded:

```text
uv run --locked --python 3.12 scripts/voice.py --script examples/script.txt --out examples/narration.m4a --timings examples/timings.json --max-seconds 57
uv run --locked --python 3.12 scripts/captions.py --audio examples/narration.m4a --script examples/script.txt --timings examples/timings.json --out examples/captions.json --srt examples/captions.srt
uv run --locked --python 3.12 scripts/cards.py --cards examples/cards.json --out-dir examples --style examples/style.json
uv run --locked --python 3.12 scripts/edit.py --plan examples/plan.json --narration examples/narration.m4a --captions examples/captions.json --out examples/explainer.mp4 --style examples/style.json
uv run --locked --python 3.12 scripts/still.py --title "Delhi NCR's air turns severe" --subtitle "An illustrative one-minute explainer" --image examples/picture.png --focus 0.4,0.5 --size 1080x1920 --style examples/style.json --out examples/still.png
```

- Voice: Kokoro-82M v1.0, int8, `af_heart`, speed 1.0, through kokoro-onnx 0.6.1 and onnxruntime 1.32.0. Captions: Whisper base.en through faster-whisper 1.2.1 and PyAV 18.1.0 on the CPU, 8-bit, no prompt. Drawing: Pillow 13.0.0, fontTools 4.68.0, Anton and Atkinson Hyperlegible. Encoding and levelling: the FFmpeg program of imageio-ffmpeg 0.8.1 (FFmpeg 9.0, which the scripts log as the one they chose), `libx264`. Every package is in the script's own `.lock` file.
- Machine: a Mac with Apple silicon. The narration took 6 seconds to speak and the video 23 seconds to draw and encode (1,611 frames), on the CPU.
- Neither the voice nor the encoder is exactly repeatable: two runs of the voice on an earlier version of this script both made 52.8 seconds with different peaks, and two runs of `edit.py` on the same inputs of an earlier version of this plan made files of 5,127,812 and 5,130,742 bytes. The committed files are the last runs, and every number below was measured on them.

## Checks

- **The words:** `captions.py` passed its gate with a word error rate of **0.040** against the limit of 0.15 (5 differences over the 126 script words), with the script as the only reference. It lists every difference on a pass as on a fail: said "Hrizzup's", heard "h rezaup's"; said "Gurugram", heard "guru graham" (twice); said "schools", heard "school's"; said "schools", heard "school". The gate treats a `{shown|spoken}` word as one word, heard right when it comes out as either form, and fails on more than the word error rate: a number in the script heard as a different number (none here: 450 was read right), or three script words in a row not heard at all. The gate was not tuned to pass. A first run of the same check on the Audio brief, on an earlier version of its script, with the script's first 200 characters given to Whisper as a prompt as the design had it, failed: Whisper took the prompt for words already said and left them out. `captions.py` now gives it no prompt.
- **The words, listened to with no prompt:** the same Whisper model, given no initial prompt at all and reading the finished `explainer.mp4` itself, heard this (verbatim, nothing corrected): "This is an illustrative sample made from H. Rezaup's example story. The air across Delhi NCR has turned severe. Before dawn on Monday, readings in Delhi, Noida and Guru Graham passed 450, the worst of the season so far. Doctors advise people with breathing problems to stay indoors. The emergency rules stop building work, keep diesel trucks out of Delhi, and ask offices to let staff work from home where they can. The school's news was corrected. On Monday, an update said schools across Delhi NCR had moved online until Friday. On Tuesday, a correction said only Delhi's primary schools have. Schools in Noida and Guru Graham remain open. What isn't confirmed is how long Delhi's primary schools stay online. The correction doesn't say. are in the post." It parts from the script in five places: "Hrizzup's", "Gurugram" (twice), "schools news" (heard as "school's news") and the last sentence's first word. The two names read as the sound of the names, so by the rule in `references/script-shape.md` (respell only what the voice itself misreads) they are the recogniser's spelling, not the voice's mistake. "Sources" is in the sound: the same model hears "Sources are in the post." when given only the last 4.4 seconds of the video (from 49.3 s), the gate's own run, with word times, placed it at 51.58 to 51.88 s, and the narration's level over 51.58 to 51.9 s is speech level (mean -13.0 dB, peak -1.5 dB). Whisper dropping a word after a pause is its habit, not the voice's.
- **Duration, size and format:** 53.7 seconds by the file's `mvhd` box (Hrizzup allows 60, the kit 58.0), 4,647,599 bytes (Hrizzup allows 100 MiB; the repository's budget for a video is 25 MiB), read with `hrizzup_media`: an MP4 with H.264 High (`avc1`, level 5.0), yuv420p, 1080 x 1920, a constant 30 frames a second (1,611 frames, which is 53.7 seconds exactly; `r_frame_rate` and `avg_frame_rate` both 30/1), BT.709 matrix, limited range, and AAC-LC 48 kHz mono (the narration, copied in), `moov` before `mdat`. The video ends with its narration.
- **Loudness, measured again after encoding:** `voice.py` measured the narration: -16.1 LUFS, true peak -1.3 dBTP (it levels again with a lower target when the encoded peak is above -1.2 dBTP). Measured again on the finished video with `hrizzup_media.loudnorm_measure`: -16.12 LUFS, true peak -1.31 dBTP, loudness range 2.9, the same as the narration file's, since the sound was copied in. A third measurement with FFmpeg 9.0.2's own `ebur128` filter (Homebrew's, not part of the kit): -16.1 LUFS, true peak -1.3 dBTP, loudness range 3.0. Hrizzup wants -17 to -15 LUFS and a true peak of -1.0 dBTP at most. FFmpeg's loudnorm used its dynamic mode (the speech's peaks are about 17 dB over its average, more than the 14.5 dB between the target level and the target peak).
- **Frames:** one at the middle of each of the eight scenes, one just after each of two caption changes, and one 0.35 seconds before the end of each of the first seven scenes (to see that nothing in a moving scene is cut off), extracted from the finished video with `ffmpeg -ss <time> -i explainer.mp4 -frames:v 1` and looked at. `edit.py` keeps each moving scene's content inside the frame: it zooms less rather than cut a card's edge off (a first render of this story's title scene, before it did, zoomed towards the left and cut the end of "SEVERE" off near the scene's end; now the end of "TURNS SEVERE" is a few percent of the frame's width from the edge). The "Corrected" scene doesn't move, since its word fills most of the card's width and a zoom would leave it about 1 percent of margin. The captions `captions.json` gives at the times:

  | Time | Frame | Caption |
  |---|---|---|
  | 4.15 s | scene 1 (title), middle | made from Hrizzup's example / story. |
  | 12.30 s | scene 2 (450+), middle | Noida and Gurugram passed 450, |
  | 18.55 s | scene 3 (doctors), middle | breathing problems to stay / indoors. |
  | 24.90 s | scene 4 (the rules), middle | keep diesel trucks out of Delhi, |
  | 32.95 s | scene 5 (the schools news), middle | On Monday, an update said / schools across |
  | 40.80 s | scene 6 (the correction, the meme), middle | a correction said only Delhi's / primary schools have. |
  | 48.05 s | scene 7 (not confirmed), middle | Delhi's primary schools stay / online. |
  | 52.50 s | scene 8 (sources), middle | Sources are in the post. |
  | 33.95 s | a caption change, just after cue 14 starts | Delhi NCR had moved online until / Friday. (the cue before: "On Monday, an update said / schools across") |
  | 47.10 s | a caption change, just after cue 19 starts | Delhi's primary schools stay / online. (the cue before: "What isn't confirmed is how long") |

  | Time | Frame | Caption |
  |---|---|---|
  | 7.95 s | scene 1, near its end | (no caption) |
  | 15.95 s | scene 2, near its end | the worst of the season so far. |
  | 20.40 s | scene 3, near its end | (no caption) |
  | 28.73 s | scene 4, near its end | (no caption) |
  | 36.48 s | scene 5, near its end | Delhi NCR had moved online until / Friday. |
  | 44.45 s | scene 6, near its end | (no caption) |
  | 50.93 s | scene 7, near its end | (no caption) |

  Each frame has the signature "Illustrative sample" at the top, the caption in the bottom fifth, and nothing cut off; the meme is whole, with bars above and below. A card's colours in the decoded frame are within two levels of the card's own (the card's black (17, 17, 17) decodes to (16, 16, 16) and its white (255, 255, 255) to (253, 253, 253), read on these frames).
- **No path in a binary:** `strings` on the video, the narration, the still and every picture here prints no home-folder path ("checked"). FFmpeg is told to write no metadata and no container encoder tag; the video's stream still carries x264's own version and settings text, and Pillow writes only the picture.
- **The pictures:** `still.png` is 1080 x 1920, 82,831 bytes; each card is 1080 x 1920 and 32,653 to 58,107 bytes (the repository's budget for a picture is 2 MiB).
- **Without the models:** both scripts take `--offline`. With an empty models folder `voice.py --offline` exits 3 and names the files it is missing and what to run (shown in the Audio brief's README), and with the real download `voice.py` and `captions.py` each fetched their models into the empty folder, checked by SHA-256 (about 136 MiB and 141 MiB).

## Why it passes its guide

- **One idea, one scene:** a title, a number, a quote, a list, the correction as one big word, the correction shown, what isn't confirmed, and the sources, each changing on a pause in the speech.
- **Every fact is in an update;** the correction is said as a correction and shown, and what isn't confirmed is its own scene and makes no guess.
- **The captions are the script's words,** timed by Whisper and kept inside each paragraph's own time by the voice's timings, not typed.
- **The meme is shown whole,** not cropped, with the captions below it.

## Results

- `explainer.mp4`: the video, 53.7 seconds, 4,647,599 bytes.
- `still.png`: the video's still, 1080 x 1920, 82,831 bytes.
- `post.json`: the post the sample would make (without its `requestId`): a video post, format `explainer`, a 581-character `body`, the five example sources behind the facts, the script's shown text as the `transcript` (760 characters), and the still's description.

## Files

- `README.md`: this file.
- `script.txt`: the script.
- `style.json`: the style with the sample signature.
- `narration.m4a`: the narration, 53.7 seconds, 632,315 bytes.
- `timings.json`: when each paragraph and chunk is spoken, from `voice.py --timings`.
- `captions.json`: the timed words and the cues, from `captions.py`.
- `captions.srt`: the cues as SubRip.
- `cards.json`: the cards file.
- `01-title.png`, `02-fact.png`, `03-quote.png`, `04-list.png`, `05-fact.png`, `06-quote.png`, `07-sources.png`: the cards `cards.py` drew.
- `meme.png`: a copy of the Meme kit's sample.
- `picture.png`: a copy of the drawing that sample was made with, used on the still.
- `plan.json`: the plan for `edit.py`.
- `explainer.mp4`: the video.
- `still.png`: the still image.
- `post.json`: the post.
