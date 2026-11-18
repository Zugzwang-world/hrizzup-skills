Illustrative: made from Hrizzup's example story, not real news; its sources are example addresses.

# Source check: a sample

A source list for Hrizzup's example story (Delhi NCR's smog and its schools), with what the optional link checker really returned for its five links.

## Input

- `brief.md`: the story's brief, as Hrizzup builds it (the same text Hrizzup's own tests use for this story). Its `## Sources` holds five links, all example addresses.

## How it was made

The post was written by hand from `brief.md`, following `references/source-list.md`, and then filled in from the link checker's real output below. Nothing in `links.json` or `live-run.json` is a prediction: both are what the script wrote.

Both runs were made from the skill's folder:

```text
uv run scripts/check_links.py --file examples/brief.md --json examples/links.json --markdown examples/links.md
uv run scripts/check_links.py https://example.com/ https://wikipedia.org/ http://example.com/ https://www.iana.org/domains/example --json examples/live-run.json
```

- Python 3.14.8 (the one uv chose; the script accepts 3.10 or newer, and was also run on 3.10), uv 0.13.1. The script uses only Python's standard library: no packages, no FFmpeg, no models.
- Machine: a Mac with Apple silicon. Date: 18 November 2026 (the runs are stamped 10:37 and 10:38 UTC).

## Results

- **The story's five links (`links.json`, 2,042 bytes; `links.md` is the same as a table, 824 bytes).** Every one came back `404` (not found), `ok: false`, no redirects, no `Last-Modified`. Each also reports the title "Example Domain": example.com and example.org answer a missing path with their usual page. That is why the post says "did not open", and not that anything is false.
- **Four pages that show the rest (`live-run.json`, 1,372 bytes):**
  - `https://example.com/`: `200`, title "Example Domain", with a `lastModified` date. It opens.
  - `https://wikipedia.org/`: `301`, one redirect followed to `https://www.wikipedia.org/`, then `200`, title "Wikipedia".
  - `http://example.com/`: no request made (`status` is `null`): the checker only checks `https://` links.
  - `https://www.iana.org/domains/example`: `301` to an `http://` address, which the checker refuses to follow (`redirects` stays 0, with the reason in `problem`).
- `post.json`: the post the sample would make (without its `requestId`): a text post, format `source-check`, 1,317 characters, four entries (one for each update, the last one a correction of the second) with the five links as its sources, and a courteous request for working ones. It says "did not open", never "verified", and never calls a claim false.
- Each run sent a `HEAD` request to every link and a `GET` where it wanted the page's title or `HEAD` was refused, to example.com, example.org, wikipedia.org, www.wikipedia.org and www.iana.org only, never more than one request to a host a second.

## Files

- `README.md`: this file.
- `brief.md`: the input.
- `links.json`: the checker's output for the story's five links.
- `links.md`: the same, as a table.
- `live-run.json`: the checker's output for the four pages above.
- `post.json`: the post.
