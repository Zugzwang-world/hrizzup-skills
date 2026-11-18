# The script of an audio brief

An audio brief is a story told to someone who is not looking at a screen. It lasts about a minute, 140 to 160 words, and it is written for the ear: short sentences, one idea at a time, the most important thing first. This guide gives its shape, how to write for the voice, and a checklist. It adds to Hrizzup's own rules (attach sources, say what is unconfirmed, give the audio its full transcript and a still image) and never replaces them.

## The shape

Write plain paragraphs separated by a blank line. Each is one beat, and the voice pauses a little longer between them.

1. **The hook** (one or two sentences). What the story is, in the words a listener would use. Not "breaking": say what happened.
2. **What happened** (two or three sentences). The newest change as facts, each with its number, unit, place and time, as the updates give them. A correction is said as a correction, and says what it corrects.
3. **What it means for you** (two or three sentences). Who is affected and what they are asked or advised to do, only as the updates say it. If the updates say nothing about it, leave the beat out.
4. **What isn't confirmed** (one or two sentences). Start "What isn't confirmed is", then say what and what would settle it. Never guess at it.
5. **"Sources are in the post."** One short sentence. Never read out a link: the links go in the post's `sources`.

## How long

- About 60 seconds, which is 140 to 160 words at the default voice and speed (a Kokoro voice speaks about two and a half words a second, plus the pauses between paragraphs). Hrizzup allows 300 seconds of audio and the script refuses past 295, but a brief that runs over 75 seconds is not a brief.
- Count the words of the shown text. If `voice.py` says the narration is over `--max-seconds`, it tells you about how many words to cut.

## Writing for the ear

- **Short sentences.** One verb, one idea. If you have to read a sentence twice, split it.
- **Say numbers the way a person would.** Write "450" and the voice reads it as "four hundred fifty". Write a year or a long number in words if you want it read a particular way.
- **Respell only what the voice itself misreads.** A word with two forms, `{shown|spoken}`, is shown (in the transcript, the post and any captions) as the left side and said as the right: `{Gurugram|Goo-roo-gram}`. Acronyms such as AQI and NCR the voice spells out by itself, so they need none. Listen to the narration, or read what a recogniser hears in it with no prompt, and change a word only if the voice said it wrong. A recogniser (the check's Whisper) spells names its own way ("Guru Graham" for Gurugram): when every word the check lists is a name the voice said right, that is the recogniser, not the voice: leave it. The check fails when the voice skips or garbles speech: three or more words in a row with nothing heard in their place, a number heard as another, or too many words changed (a name heard as another word counts only toward the last).
- **No symbols, no links, no brackets, no tables.** Write "percent" and "rupees" (or "Rs"), not the symbols. Write the words, not a layout.
- **Times and dates the way you say them:** "before dawn on Monday", "until Friday". Give a zone when it matters.
- **English only for now.** The voice and the fonts read English (Latin letters); Hindi and other scripts are refused (exit 2).
- **Names, places, numbers and dates exactly as the updates give them.** Say only what the updates say.

## What the voice is

`voice.py` reads the script with Kokoro-82M. `af_heart` is the default; `af_bella`, `bf_emma` (British), `am_michael`, `am_fenrir` and `bm_george` are the others. Pick one voice and keep it: a creator is recognised by its voice. `--speed` 0.85 to 1.15 changes the pace; leave it at 1.0 unless the script is a little too long and slightly faster is honest. It never trims or speeds speech to fit.

## Good and bad

- Bad hook: "A dramatic day in the capital." Good hook: "Delhi's air has turned severe."
- Bad: "Pollution levels were a hundred-plus points past the safe limit, per the CPCB's AQI table." Numbers and a source the updates don't give.
- Good: "Readings in Delhi, Noida and Gurugram crossed 450, the worst of the season so far."
- Bad: "Schools are closed." Good: "On Tuesday, a correction said only Delhi's primary schools have moved online. Schools in Noida and Gurugram remain open."
- Bad: "It will all be over by Friday." Nothing says so. Good: "What isn't confirmed is how long Delhi's primary schools stay online. The first update said until Friday, but the correction doesn't repeat it."

## Checklist

- [ ] The first sentence says what the story is, and the newest change comes next.
- [ ] Every fact, number and time is in an update, with its unit and place.
- [ ] A correction is said as a correction.
- [ ] What isn't confirmed is its own beat, and nothing in it is a guess.
- [ ] 140 to 160 words, short sentences, no link read aloud, no symbol the voice can't say.
- [ ] Only a word the voice itself misreads has a spoken form (`{shown|spoken}`); names the recogniser spells its own way are left alone.
- [ ] "Sources are in the post." is the last sentence, and the post's `sources` hold the links.
- [ ] After `voice.py`: the length and loudness it printed are in range, and the still's title fits.
- [ ] The post's `body` is at most 1,000 characters, the `transcript` is the script's shown text, and the still has a `description`.
