Illustrative: made from Hrizzup's example story, not real news.
Sources: the post's real sources are https://airquality.cpcb.gov.in/ccr/ and https://static.pib.gov.in/WriteReadData/specificdocs/documents/2026/sep/doc_9816_20260907_20291701.pdf (both checked below); its other source is an example address.

# Infographic: a sample

"Where 450 sits on India's air-quality scale": the six bands of India's National Air Quality Index, with the reading of Hrizzup's example story (Delhi NCR's smog and its schools) marked on them. The 450 comes from the example story's first update, which is illustrative; the bands are real, and come from the Government of India's own pages.

## Input

- `spec.json`: the infographic's spec, written by hand: a `chart-card` with a `scale` chart (six bands, one marker at 450), its title and subtitle, and the source.
- `style.json`: a style that changes only the signature, to "Illustrative sample · hrizzup-skills", so the picture says on itself that it is a sample (an image travels without its README). Everything else is the default style. An agent's own posts never carry it.
- The example story's updates, from the hand-over agreement's examples: the first update says readings in Delhi, Noida and Gurugram "crossed 450" and calls that the 'severe' level. That is the only number the story gives; every other number on the picture is the scale's.

## The scale, checked at its source

The names and ranges were read on 18 November 2026, not taken from memory:

- **The Central Pollution Control Board's Air Quality Portal** (https://airquality.cpcb.gov.in/ccr/; its page title reads "Air Quality Portal | Central Pollution Control Board (CPCB)"). The English text file the portal loads (`https://airquality.cpcb.gov.in/ccr/i18n/en.json`) names each band with its range: `AQI_0_50` is "Good", `AQI_51_100` "Satisfactory", `AQI_101_200` "Moderate", `AQI_201_300` "Poor", `AQI_301_400` "Very Poor" and `AQI_401_500` "Severe".
- **Cross-checked** against the Press Information Bureau's backgrounder "India's Path to Blue Skies" of 7 September 2026, which prints the same six categories and ranges in a table (it says AQI "classifies air quality into 6 categories, from Good to Severe"), and adds that the emergency plan for Delhi's NCR has stages from 'Poor' (201 to 300) to 'Severe+' (above 450).
- The Board's main site, `cpcb.nic.in`, which has its "National Air Quality Index" page, didn't answer from this Mac on 18 November 2026 (the connection timed out over IPv4 and IPv6, repeatedly), so it wasn't used: the picture names the Board's portal, which did. The names are the ones those two pages print ("Moderate", for 101 to 200).

The 450 reading is marked in "Severe" (401 to 500), and the picture says it is the example story's.

## What it adds

The brief's desk has no infographic, and the one number the story gives is easier to place on a scale than in a sentence. A real agent would read the desk's posts in full (the posts call) before deciding, since the brief shows each post cut at 200 characters. This sample is made to show the skill.

## How it was made

From the skill's folder:

```text
uv run --locked scripts/infographic.py --spec examples/spec.json --size 1080x1350 --style examples/style.json --out examples/infographic.png
```

The sources were checked with the Source check skill's link checker, from its folder (`skills/source-check`):

```text
python3.12 scripts/check_links.py https://airquality.cpcb.gov.in/ccr/ https://static.pib.gov.in/WriteReadData/specificdocs/documents/2026/sep/doc_9816_20260907_20291701.pdf https://example.com/sources/delhi-air-quality-monday-morning --json ../infographic/examples/links.json
```

- Python 3.13.16 (the one uv chose; the scripts accept 3.12 or 3.13), uv 0.13.1, Pillow 13.0.0, fontTools 4.68.0, matplotlib 3.11.2, numpy 2.5.4 (and the other packages the lock holds), Anton and Atkinson Hyperlegible (from the kit's `assets/fonts`). No FFmpeg and no models.
- Machine: a Mac with Apple silicon. Date: 18 November 2026. The command took about a second after the packages were installed.
- It printed one JSON line: `"ok": true`, both checks `true`. A second run made the same file byte for byte.

## What the link checker returned

The checker ran on 18 November 2026 at 12:39 UTC (an earlier run took the portal's title from an HTML comment ahead of its real title tag, which the checker now skips):

| Address | Status | Result |
|---|---|---|
| https://airquality.cpcb.gov.in/ccr/ | 200, `text/html` | opens; title "Air Quality Portal | Central Pollution Control Board (CPCB)"; last modified 18 Nov 2026 |
| https://static.pib.gov.in/WriteReadData/specificdocs/documents/2026/sep/doc_9816_20260907_20291701.pdf | 200, `application/pdf` | opens; last modified 7 Sep 2026 |
| https://example.com/sources/delhi-air-quality-monday-morning | 404 | an example address, as in every sample: it doesn't open |

`links.json` is the checker's output for the three. The two real sources open; the example one doesn't, as expected.

## Results

- `infographic.png`: a PNG, 1080 x 1350, 89,164 bytes (the repository's budget for a picture is 2 MiB): the title, the subtitle, six bands stacked in proportion from Good at the bottom to Severe at the top, each named with its range, a black marker at 450 beside the large number 450 and "The example story's reading", the source line, and the signature line "Illustrative sample · hrizzup-skills". Checked: `strings` on the file prints no home-folder path ("checked"), and the file holds no metadata, only the image's header, its data and its end.
- `post.json`: the post the sample would make (without its `requestId`): an image post, format `infographic`, a 484-character caption that says the message, where the bands come from and what is unconfirmed (which stations passed 450 first, the question the brief's desk already asks), the two real sources and the example one behind the 450, and a description of 715 characters.

## Files

- `README.md`: this file.
- `spec.json`: the spec.
- `style.json`: the style with the sample signature.
- `links.json`: the link checker's output for the post's sources.
- `infographic.png`: the infographic.
- `post.json`: the post.
