# The script of an explainer video

An explainer is one story told in a minute, one idea at a time. Each paragraph of the script is one idea, and each idea gets a scene: a card or a picture on screen while the voice says it. The video is 45 to 58 seconds, which is 110 to 145 words. This guide gives the shape, how to write for the voice and the screen together, and a checklist. It adds to Hrizzup's own rules (attach sources, say what is unconfirmed, give the video its full transcript and a still image) and never replaces them.

## The shape

Write plain paragraphs separated by a blank line, five to seven of them. The voice pauses a little longer between paragraphs, which is where the picture changes.

1. **The hook** (one or two sentences). What the story is. A sample made for this repository opens by saying it is an illustrative sample; your own explainer opens on the story.
2. **What happened** (one to three paragraphs). The newest change as facts, each with its number, unit, place and time, as the updates give them. A correction is said as a correction, and a picture of it follows it.
3. **Why it matters** (one paragraph, if the updates say it). Who is affected and what they are asked to do, only as the updates say it.
4. **What isn't confirmed** (one short paragraph). Start "What isn't confirmed is", then say what. Never guess.
5. **"Sources are in the post."** The last, shortest paragraph, over a card that lists the sources.

## One idea, one scene

- A scene shows what the paragraph says and no more: a big number, a short list, a correction, a picture you made. The card carries a few words; the voice carries the rest. Never put the paragraph itself on screen: the captions already do.
- Plan the scenes from `voice.py --timings`: it says when each paragraph starts and ends. A paragraph of 12 seconds can be two scenes. The last scene takes whatever is left of the narration and needs at least a second.
- Change the picture on the pause between paragraphs, so the picture and the voice change together.

## How long

- 110 to 145 words, 45 to 58 seconds. A Kokoro voice speaks about two and a half words a second, plus 0.6 seconds between paragraphs. A video is at most 58.0 seconds by its own length (Hrizzup allows 60), so run `voice.py --max-seconds 57`.
- If `voice.py` says the narration is over, it tells you about how many words to cut. Cut a sentence, not a syllable: speech is never trimmed or sped up to fit.

## Writing for the voice

- **Short sentences,** one idea each. Numbers as digits ("450"): the voice says "four hundred fifty".
- **Acronyms and names the voice may misread** get a spoken form: `{AQI|A Q I}`, `{NCR|N C R}`. The captions and the transcript show the left side; the voice says the right.
- **No links, no symbols, no tables.** Links go in the post's `sources`.
- **Times and dates as you say them:** "before dawn on Monday", "until Friday".
- **English only for now:** the voice and the fonts read English (Latin letters).
- **Names, places, numbers and dates exactly as the updates give them.** Say only what the updates say.

## Good and bad

- Bad: a scene that reads out the paragraph. Good: a card with "450+" and the words "Air quality", while the voice says what crossed 450.
- Bad: a correction said but not shown. Good: the correction on screen while it is said, in the words the update uses.
- Bad: "Experts say this is only the beginning." Nobody in the updates says so.
- Bad: "Schools are closed." Good: "On Tuesday, a correction said only Delhi's primary schools have moved online. Schools in Noida and Gurugram remain open."

## Checklist

- [ ] The first sentence says what the story is, and the newest change comes next.
- [ ] Every fact, number and time is in an update, with its unit and place; a correction is said and shown.
- [ ] What isn't confirmed is its own paragraph, and nothing in it is a guess.
- [ ] 110 to 145 words, five to seven paragraphs, a scene for each idea, the last scene at least a second long.
- [ ] No link read aloud; acronyms and names the voice may misread have a spoken form.
- [ ] After `voice.py`: the length is at most 57 seconds and the loudness is in range. After `captions.py`: the word error rate passed, and the captions show the script's words.
- [ ] After `edit.py`: frames from the start, the middle and the end of each scene show the picture, the signature and the caption, and nothing is cut off.
- [ ] The post's `body` is at most 1,000 characters, the `transcript` is the script's shown text, and the still has a `description`.
