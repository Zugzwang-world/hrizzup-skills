# Writing a source list: the desk editor's guide

A source list shows a reader the link behind every claim in a story, says what is known about each link, and asks for a source where there isn't one. Think of it as the page a fact-checker would hand an editor: short, exact and fair. It makes no accusations. It says what each link is, what was checked, and what is still missing.

The rule underneath: **say only what you did.** A link you did not open is "not opened", never "checked". A claim with no link is "no source given", never "false".

## The list

Write one entry for each claim, in the order the claims appear in the story's timeline (oldest first). Use this shape:

```text
Sources for "<story title>", from the brief of <date>.

1. <the claim, in the update's own words, with its time and zone>
   Link: <the address, exactly as the update gives it>
   Checked: <what you did, in one phrase>

2. <the next claim> ...
   No source given.

Please send: <a working source for each claim that has none, or whose link didn't open>.
```

- **Claim.** One factual statement, taken from the update, with the time and zone of the update. Don't rewrite it into something stronger.
- **Link.** The address exactly as published: no shortening, no tracking, no change of case. Give every link the update lists, in its order. A link that comes from a post or a group rather than an official body is still listed; say what kind of page it is only if the link or its page says so.
- **Checked.** What you did and what you saw, in one short phrase, in one of these four ways, and nothing more:
  - `Opened and read.` You opened the page and read it. Say what it says in a few words.
  - `Opened (200), not read for the claim.` The link checker reached it. This says the page exists, not that it supports the claim.
  - `Did not open (404, not found).` Give the status and its meaning, or the reason the checker reports. When an entry has several links and they all failed the same way, one phrase can say so: `Neither opened (404, not found).`
  - `Not opened.` You didn't try, or couldn't. This is the honest default.
- **No source given.** When an update lists no link, write exactly that, and ask for one at the end.

## The desk's rules

- **Say only what you did.** "Opened" and "not opened" are facts about your work. "Reliable", "fake" and "confirmed" are judgments you can't make from a link's status.
- **A page that opens is not a page that supports the claim.** Say whether you read it. If you only saw a status, say that.
- **A dead link is a finding, not a verdict.** A 404 means the page is gone or the address is wrong; it doesn't mean the claim is false. Say "did not open" and ask for a working source.
- **Don't invent a source.** Never fill a gap with a link you think should be right, or one you found yourself unless you say so and attach it as yours.
- **Courtesy.** The tone is a colleague's: "Could the desk send a working link for this?" not "Unsourced!"
- **Corrections count.** If an update corrects another, list both claims, in order, and say which corrects which. A correction needs a source as much as the claim it corrects.
- **Be kind to sites.** Check each link once. Don't hammer one host.

## Where the links come from

The story's brief: each update's line in `## Timeline` and the addresses under `## Sources`. If you were asked to check a particular post, take the links from that post as well, and mark which come from the post and which from the brief. The brief lists every update's links, once each.

## The optional checker

If you can run scripts, `scripts/check_links.py` (`uv run scripts/check_links.py --file brief.md --json links.json --markdown links.md`) opens each link for you and reports its status, where it ended up after any redirects, its content type, its page title and when the page was last modified. It makes `HEAD` and `GET` requests, one request to a host a second, never opens an `http://` link or an address on a private network, and exits 0 even when links fail. Its status tells you the page exists, not what it says: read the page before you write "Opened and read". Without it, write "Not opened" and leave it there.

## Before you post

- [ ] One entry for each claim, oldest first, each with its time and zone.
- [ ] Every link is exactly as the update gives it.
- [ ] Every "Checked" line says only what you did.
- [ ] Every claim without a link says "No source given" and is asked for at the end.
- [ ] The tone is courteous, and nothing is called false or fake.
- [ ] The post's sources are the links you list, at most ten.

## Good and bad, from the example story

The example story is Hrizzup's own: Delhi NCR's smog and its schools. Its sources are example addresses.

**An entry**

- Bad: `Smog claim: fake, link is dead.` A dead link doesn't make a claim fake.
- Good: `1. 2 Nov, 07:00 IST: air quality across Delhi NCR falls to 'severe' as readings pass 450. Link: https://example.com/sources/delhi-air-quality-monday-morning. Checked: did not open (404, not found).`

**What was done**

- Bad: `Checked: all sources verified.` You verified nothing by reading a status.
- Good: `Checked: not opened.`, or `Checked: opened (200), not read for the claim.`

**Corrections**

- Bad: listing only the correction, as if the first claim never happened.
- Good: list the 11:35 IST schools claim and the 3 Nov, 09:20 IST correction as two entries, and say which corrects which.

**Asking**

- Bad: `Needs a source.` Who? For what?
- Good: `Please send: a working link for each of the five claims above; none of their links opened when I checked.`
