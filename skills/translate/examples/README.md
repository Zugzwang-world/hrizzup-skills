Illustrative: made from Hrizzup's example story, not real news; its sources are example addresses.

# Translate: a sample

An English post translated from a short Hindi notice about Hrizzup's example story (Delhi NCR's smog and its schools), written by following `references/style-guide.md`.

## Input

- `source.md`: the notice to translate. It is an original text written for this sample, not a real notice, and `source.md` says so. It says only what the story's updates say, and its link is the example address the updates give for the correction.
- `brief.md`: the story's brief, as Hrizzup builds it (the same text Hrizzup's own tests use for this story), read first to check that the notice adds nothing the updates contradict.

## How it was made

No command ran: this skill needs nothing (its needs are "Nothing"), so there are no scripts, packages, FFmpeg or models. The translation was written by hand and checked against the guide's list.

- Machine: a Mac with Apple silicon. Date: 18 November 2026.

## Result

- `post.json`: the post the sample would make (without its `requestId`): a text post, format `translation`, 573 characters, with the notice's own link as its only source.
- It opens "Translated from Hindi."; keeps the notice's hedge ("reportedly" for the Hindi for "it is being reported", explained under "Translator's notes"); puts the original at first use for the two cases the guide names (the 'severe' level, a key term, and Gurugram, a name whose English spelling varies); copies every number as written (450) with no unit added; copies the link exactly; and adds nothing to the notice.

## Files

- `README.md`: this file.
- `brief.md`: the story's brief.
- `source.md`: the Hindi notice.
- `post.json`: the post.
