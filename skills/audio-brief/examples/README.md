Illustrative: made from Hrizzup's example story, not real news.
Sources: the post's sources are all example addresses.

# Audio brief: a sample

A one-minute audio brief on Hrizzup's example story (Delhi NCR's smog and its schools), made by following `references/script-shape.md`: a hook, what happened, what it means for you, what isn't confirmed, and "Sources are in the post." The narration says it is an illustrative sample in its first sentence, and the still image carries "Illustrative sample" on itself, since each travels without this README.

## Input

- The story's updates, from the hand-over agreement's examples (the same live updates the other samples use): the air-quality update of 2 Nov (readings past 450 in Delhi, Noida and Gurugram before dawn on Monday, the worst of the season so far; doctors advise people with breathing problems to stay indoors), the emergency-rules update (building work stops, diesel trucks kept out of Delhi, offices asked to let staff work from home where they can), the schools update (schools across Delhi NCR move online until Friday) and the correction of 3 Nov (only Delhi's primary schools; Noida and Gurugram stay open). Nothing in the script goes beyond them.
- `script.txt`: the script, 146 words in six paragraphs. Two words have a spoken form: `{Hrizzup's|Hrizz-up's}` and `{Gurugram|Goo-roo-gram}`, because the voice's own reading of each came out wrong when tried (Whisper heard "Hrizzup's" as "Przup's" and "Gurugram" as "Geogram"); the captions and the transcript show the left side. AQI and NCR need none: the voice spells them out by itself. Sources are never read out: they are in the post.
- `style.json`: a style that changes only the signature, to "Illustrative sample", so the still says on itself that it is a sample. Everything else is the default style. An agent's own posts never carry it.

## What it adds

The brief's desk has a video and a timeline but no audio brief, so a brief adds something. A real agent would read the desk's posts in full before deciding (the posts call), since the brief shows each post cut at 200 characters. This sample repeats the story's own updates on purpose, to show the skill.

## How it was made

All from the skill's folder, with uv 0.13.1 on Python 3.12.3 (`--python 3.12`; the scripts accept 3.12 or 3.13), on 18 November 2026. The first run had `HRIZZUP_MODELS_DIR` pointing at an empty folder, so the models were downloaded by the scripts themselves; the committed narration is the fourth run, which used them from there:

```text
uv run --locked --python 3.12 scripts/voice.py --script examples/script.txt --out examples/narration.m4a --timings examples/timings.json
uv run --locked --python 3.12 scripts/still.py --title "Delhi's air turns severe" --subtitle "An illustrative one-minute audio brief" --size 1080x1080 --style examples/style.json --out examples/still.png
```

- Voice: Kokoro-82M v1.0, int8, `af_heart`, speed 1.0, through kokoro-onnx 0.6.1 and onnxruntime 1.32.0 (the packages are in `scripts/voice.py.lock`). The two model files (about 136 MiB) came from the kokoro-onnx release and were checked by their SHA-256. The narration was levelled with the FFmpeg program of imageio-ffmpeg 0.8.1 (FFmpeg 9.0, which `voice.py` logs as the one it chose).
- Pillow 13.0.0, fontTools 4.68.0, Anton and Atkinson Hyperlegible (from the kit's `assets/fonts`) drew the still. No models.
- Machine: a Mac with Apple silicon. The narration took 7 seconds to speak, on the CPU.
- The voice is not exactly repeatable. Four runs of this script made 61.2, 61.1, 61.1 and 61.1 seconds, with peaks before levelling between -7.6 and -8.5 dBTP and files of 725,637 to 726,263 bytes. The committed narration is the last run, and every number below was measured on it.

## Checks

- **The words:** Whisper base.en through `captions.py` (the explainer-video skill's kit, which the Audio brief's leaves out; its command, from that skill's folder: `uv run --locked --python 3.12 scripts/captions.py --audio ../audio-brief/examples/narration.m4a --script ../audio-brief/examples/script.txt --timings ../audio-brief/examples/timings.json --out captions.json`, written to a scratch folder and not kept) passed its gate (with `--timings examples/timings.json`, so no word is shown outside its paragraph): a word error rate of **0.065** against the limit of 0.15 (10 of the 153 spoken words), with the script as the only reference. The words that didn't match are the names: Hrizzup's, Gurugram (twice) and one "schools". The gate was not tuned to pass: its normalisation (numbers as words, spelled letters joined) is general, and 450 and AQI were read without an error. A first run of the same check, with the script's first 200 characters given to Whisper as a prompt as the design had it, failed (0.28): Whisper took the prompt for words already said and left the first 30 words out. `captions.py` now gives it no prompt.
- **The words, listened to with no prompt:** the same Whisper model, given no initial prompt at all, heard this (verbatim, nothing corrected): "This is an illustrative sample made from H. Rezaup's example story. Delhi's air has turned severe. Before dawn on Monday, AQI readings in Delhi, Noida and Guru Graham crossed 450, the worst of the season so far. The city's emergency rules are in force. Building work has stopped, and diesel trucks are kept out of Delhi. What does this mean for you? Doctors advise people with breathing problems to stay indoors. The emergency rules also ask offices to let staff work from home where they can. Schools changed twice. On Monday, an update said schools across Delhi NCR had moved online until Friday. On Tuesday, a correction said only Delhi's primary schools have. Schools in Noida and Guru Graham remain open. What isn't confirmed is how long Delhi's primary schools stay online. The first update said until Friday, but the correction doesn't repeat it. Sources are in the post." The names are the only places it parts from the script.
- **Duration and size:** 61.1 seconds by the file's `mvhd` box (Hrizzup allows 300, the kit 295), 725,678 bytes (Hrizzup allows 20 MiB; the repository's budget for audio is 5 MiB), read with `hrizzup_media`: M4A with the brand `M4A `, AAC-LC, 48 kHz, mono, 93 kb/s (`ffprobe`), written with `+faststart`.
- **Loudness, measured again after encoding:** `voice.py` measured the finished file: -16.1 LUFS, true peak -1.3 dBTP. Measured again afterwards with `hrizzup_media.loudnorm_measure`: -16.09 LUFS, true peak -1.31 dBTP, loudness range 4.1. Measured a third time with FFmpeg 9.0.2's own `ebur128` filter (Homebrew's, not part of the kit): -16.1 LUFS, true peak -1.3 dBTP, loudness range 3.5. Hrizzup wants -17 to -15 LUFS and a true peak of -1.0 dBTP at most. FFmpeg's loudnorm used its dynamic mode for the second pass (the speech's peaks are about 17 dB over its average, more than the 14.5 dB between the target level and the target peak, so a straight gain would break the peak limit), and the encoded file's peak can come out above the -1.5 dBTP asked for, as the AAC encoder adds to it; `voice.py` levels again with a lower target when the encoded peak is above -1.2 (the limit is -1.0).
- **No path in a binary:** `strings` on `narration.m4a` and on `still.png` prints no home-folder path ("checked"). Neither holds metadata: FFmpeg is told to write none (no copied metadata, no encoder tag), and Pillow writes only the picture.
- **The still:** `still.png` is 1080 x 1080, 26,390 bytes, a PNG (the repository's budget for a picture is 2 MiB), read with `hrizzup_media`.
- **Without the models:** the same `voice.py` command with `--offline` against an empty models folder exits 3 and says which files are missing, that `--offline` was given, how much it would download (about 136 MiB) and to run it once without `--offline`. With the real download into that empty folder it fetched both Kokoro files in about 30 seconds and made the first of the four narrations.

## Why it passes its guide

- **The first sentence says what the story is,** after saying it is a sample, and the newest change follows.
- **Every fact is in an update,** with its number and place; the correction is said as a correction.
- **What isn't confirmed is its own beat,** and says so without a guess.
- **No link is read out,** and nothing leaves the updates.

## Results

- `narration.m4a`: the narration, 61.1 seconds, 725,678 bytes.
- `still.png`: the audio's still, 1080 x 1080, 26,390 bytes.
- `post.json`: the post the sample would make (without its `requestId`): an audio post, format `audio-brief`, a 503-character `body`, the five example sources behind the facts, the script's shown text as the `transcript` (875 characters), and the still's description.

## Files

- `README.md`: this file.
- `script.txt`: the script.
- `style.json`: the style with the sample signature.
- `narration.m4a`: the narration.
- `timings.json`: when each paragraph and chunk of the script is spoken, from `voice.py --timings`.
- `still.png`: the still image.
- `post.json`: the post.
