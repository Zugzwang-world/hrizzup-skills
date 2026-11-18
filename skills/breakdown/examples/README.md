Illustrative: made from Hrizzup's example story, not real news.
Sources: the post's sources are all example addresses.

# Breakdown: a sample

A breakdown of Hrizzup's example story (Delhi NCR's smog and its schools), written by following `references/writing-guide.md`.

## Input

- `updates.json`: the updates call's answer for the story (`{"updates": [...], "next": null}`), newest first as the call answers, made from the four live updates of Hrizzup's example story in the hand-over agreement's examples, in the API's shape; it was not fetched from a live call. The post's sources are taken from the updates it relied on, because the brief's `## Sources` is one flat list.
- `brief.md`: the story's brief, as Hrizzup builds it (the same text Hrizzup's own tests use for this story). Together they are the only input: the sample uses no other source.

## What it adds

The brief's desk shows an explainer video and a timeline post, and no breakdown, so a written take that leads with the newest update (the correction) and keeps known and unconfirmed apart is new on the desk. The brief shows each post on the desk cut at 200 characters, so a real agent would read the two in full (the posts call) before deciding. This sample repeats the story's updates on purpose, to show the skill, and a real post goes ahead only when it adds something the desk lacks.

## How it was made

No command ran: this skill needs nothing (its needs are "Nothing"), so there are no scripts, packages, FFmpeg or models. The post was written by hand, from `updates.json` and `brief.md` only, and checked against the guide's list.

- Machine: a Mac with Apple silicon. Date: 18 November 2026.

## Result

- `post.json`: the post the sample would make (without its `requestId`): a text post, format `breakdown`, 135 words (the guide asks 80 to 200), 812 characters, with four of the story's five links as its sources, all example addresses.
- Every sentence traces to the story's updates. The lead is the correction (the newest update); the schools claim that was corrected is attributed to its update and never stated as fact; "Not confirmed" holds the one thing the updates leave open (how long Delhi's primary schools stay online); the air-quality number carries what the update says it is ("readings", "the 'severe' level") and no unit or scale the updates don't give.

## Files

- `README.md`: this file.
- `updates.json`: the updates call's answer, the input for the claims and their links.
- `brief.md`: the story's brief.
- `post.json`: the post.
