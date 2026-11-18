Illustrative: made from Hrizzup's example story, not real news; its sources are example addresses.

# Breakdown: a sample

A breakdown of Hrizzup's example story (Delhi NCR's smog and its schools), written by following `references/writing-guide.md`.

## Input

- `brief.md`: the story's brief, as Hrizzup builds it (the same text Hrizzup's own tests use for this story). It is the only input: the sample uses no other source.

## How it was made

No command ran: this skill needs nothing (its needs are "Nothing"), so there are no scripts, packages, FFmpeg or models. The post was written by hand, from `brief.md` only, and checked against the guide's list.

- Machine: a Mac with Apple silicon. Date: 18 November 2026.

## Result

- `post.json`: the post the sample would make (without its `requestId`): a text post, format `breakdown`, 135 words (the guide asks 80 to 200), 812 characters, with four of the story's five links as its sources, all example addresses.
- Every sentence traces to the story's updates. The lead is the correction (the newest update); the schools claim that was corrected is attributed to its update and never stated as fact; "Not confirmed" holds the one thing the updates leave open (how long Delhi's primary schools stay online); the air-quality number carries what the update says it is ("readings", "the 'severe' level") and no unit or scale the updates don't give.

## Files

- `README.md`: this file.
- `brief.md`: the input.
- `post.json`: the post.
