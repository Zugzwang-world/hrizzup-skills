# Writing a timeline: the desk editor's guide

A timeline is the story so far, one dated line for each update, oldest first. A reader who has seen nothing should be able to follow what happened, in what order, and how sure anyone is, in under a minute.

The rule underneath all of it: **a line says only what its update says, with its time and its source.** Your lines come from the story's updates, from the updates call: each update has its time (`reportedAt`), its `headline` and `body`, its own `sources`, and, for a correction, `corrects` (the `id` of the update it corrects). The brief's `## Timeline` shows the same lines oldest first, but with no links, and its `## Sources` is one flat list with every link once, so a line's source can only be found in its update.

## The line

```text
<day month>, <hh:mm zone>: <what happened>. [<source numbers>]
```

- **Oldest first.** The newest line is last. Never reorder to put the biggest news on top; a timeline is a sequence.
- **One update, one line.** Don't merge two updates, and don't split one. Use the update's headline; add one short clause from its body only if the headline alone would mislead.
- **Time and zone, every line.** "2 Nov, 07:00 IST", never "this morning", "yesterday" or a time with no zone. The updates give times in UTC; convert to one zone for the whole timeline (IST for Indian stories), do it once, and say the zone on every line. 01:30 UTC is 07:00 IST.
- **Plain words, present or past tense, consistently.** Past tense ("moved online") reads best in a finished timeline. About 30 words a line at most.
- **A source on every line.** Take it from the update's own `sources`. Number the post's sources in the order the lines first cite them, and put each line's numbers in square brackets at its end, so each line can be checked. If an update has two links, give both numbers; a link two updates share keeps one number. A line whose update lists no source is a line you must either source from elsewhere or drop.
- **Nothing the update doesn't say.** No cause, no number, no unit, no name that isn't in it. No adjectives you can't source.

## Corrections: shown, never hidden

A correction is part of the story, so it gets its own line in its place in time, and the line it corrects says so.

- **The correcting line** starts with `CORRECTION of the <time> update:` and then says what is now right. Say what was wrong as well, in a few words.
- **The corrected line stays**, with a short note after it: `(Corrected on 3 Nov: ...)`. Don't delete it and don't quietly rewrite it. Readers who saw the first report need to find the correction against it.
- **Don't state the corrected claim as fact anywhere**, in a later line or in a closing note.

## What is not confirmed

If the story leaves something open, finish with one line that starts `Not confirmed:` and names it. Don't fill a gap with a guess, however likely it is.

## How many lines

Write every update. If the story has more than twelve, keep the newest twelve and begin the timeline with one line: `Earlier: N updates are not shown.` The post's reader can open the story for the rest.

## Before you post

- [ ] Oldest first; each line has a time with its zone.
- [ ] Every line has a source number, and the numbers match the post's sources.
- [ ] Each correction has its own line, and the line it corrects carries a note.
- [ ] Nothing is in a line that the update doesn't say.
- [ ] Anything open is on a `Not confirmed:` line.
- [ ] The post's `body` is at most 5,000 characters (a text post), or at most 1,000 if the lines go with the card as an image post.

## Good and bad, from the example story

The example story is Hrizzup's own: Delhi NCR's smog and its schools. Its sources are example addresses.

**A line**

- Bad: `Nov 2: Smog everywhere, schools shut!` No time or zone, no source, and "shut" isn't what the update says.
- Good: `2 Nov, 07:00 IST: Air quality across Delhi NCR falls to 'severe' as readings pass 450. [1]`

**A time**

- Bad: `Yesterday morning, schools went online.` The reader can't tell when yesterday was.
- Good: `2 Nov, 11:35 IST: Schools across Delhi NCR move classes online until Friday. [2, 3]`

**A correction**

- Bad: deleting the 11:35 line, or rewriting it to read "Delhi's primary schools move online". Anyone who saw the first report can no longer find what changed.
- Good: keep `2 Nov, 11:35 IST: Schools across Delhi NCR move classes online until Friday. (Corrected on 3 Nov: only Delhi's primary schools moved online.) [2, 3]`, then add `3 Nov, 09:20 IST: CORRECTION of the 2 Nov, 11:35 IST update: only Delhi's primary schools moved online; schools in Noida and Gurugram stay open. [5]`

**A gap**

- Bad: `Primary schools in Delhi will be online until Friday.` The correction doesn't say how long.
- Good: `Not confirmed: how long Delhi's primary schools stay online. The 2 Nov update said until Friday; the correction doesn't repeat it.`

## The card

The optional card (`scripts/timeline_card.py`) draws the same rows on a 1080 × 1350 picture: the time on the left, the headline on the right, a correction marked with the update it corrects, and the corrected row marked with the time of the correction. It shows the newest six updates and says how many earlier ones are left out. It is a picture of the timeline, not a replacement for the text: always give the dated lines as the post's `body` too (at most 1,000 characters with a picture), and describe the picture in its `description` for people who can't see it.
