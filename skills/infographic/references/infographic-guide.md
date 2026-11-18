# Making an infographic: the desk editor's guide

An infographic is one picture that shows readers something a paragraph shows badly: a size, a comparison, a change over time, a position on a scale, a few steps. A reader who has seen nothing should get its one message in five seconds, and know where the numbers come from.

The rule underneath all of it: **one message a graphic, and every number on it from a source named on the image.**

## One message

- **Say the message in the title.** "Where 450 sits on India's air-quality scale" tells a reader what to look for; "Air quality" tells them nothing. A title is a sentence about the picture, in two lines at most.
- **One chart, one comparison.** If you need two messages, make two graphics. Cut every bar, line or label that doesn't carry the message.
- **Pick the shape the message needs:**
  - how big is one thing: a big number (`stat-card`);
  - how do things compare: bars (`bar`, lying down, for names that need room) or columns (`column`, standing up, for a few short labels);
  - how did it change: a line (`line`);
  - where does a reading fall in a range with named bands: a scale (`scale`);
  - what to do, or what happened in order: steps (`steps-card`, two to five).
- **Say it is illustrative** when the figures are made up for a test or a sample, on the image itself.

## Honest charts

- **Bars start at zero.** Always, with no cut in the middle and no broken axis. A bar's length is the number; start it anywhere else and the picture lies. `infographic.py` draws every bar and column from zero and refuses negatives (there is no length to draw): show those as a line, or write them in the post.
- **A line may start above zero only if the picture says so.** `"from_zero": false` writes "The axis does not start at zero" on the chart. Use it rarely.
- **No 3-D, no shadows, no dual axes.** Two different scales on one chart let anyone make two lines cross where they like. Make two charts, or index both to the same start and say so.
- **Direct labels.** Put each value on its bar, column or point, and name each mark where it is. Don't send readers to a legend or a grid to look numbers up. The script labels every bar and column, the first and last point of a line (and any you highlight), and every band of a scale.
- **Order matters.** Bars in the order the data has (a ranking, a timeline, a named list), and say which. Highlight at most three marks: the one the message is about.
- **Few, round, real.** Show the numbers the story gives, rounded no further than the source rounds them. Never show a figure the updates or your sources don't hold, and never a forecast as a fact.

## Units, time and the thing measured

- **Units on every number.** "462 AQI", "12.5%", "3 days": the `unit` of a chart is added to every value label; or give a value its own `text` ("1.2 lakh") when the unit is more than a suffix.
- **Say what is measured, where and when.** "Readings across the NCR on Monday" beats "Readings". If the figure is an average, a peak or a single station, say which, in the subtitle.
- **Name the scale.** A band or a category gets the name its official source gives it, with the range as the source prints it; don't rename or merge bands.

## The source goes on the image

An image travels without its post. Every infographic carries its source in the picture's own words (`"source"` in the spec is required): who published the numbers, and what they are. A link doesn't fit a picture, so name the publisher and the page ("Central Pollution Control Board, Air Quality Portal"), and put the link in the post's sources. Say plainly when a number comes from elsewhere ("The 450 reading is from Hrizzup's example story"), and when something is unconfirmed, say that too.

## Words, colour and size

- **Plain English words, no emoji.** The fonts draw English (Latin) letters, digits and common punctuation only. Hindi and other scripts are refused for now, and so are emoji and the symbols for the rupee, left and right arrows: write the words in English, and `Rs` or `INR`, and "to". The script refuses a character the font lacks.
- **Short labels.** Two lines at most for a bar's name, three for a column's. The script fits them and tells you how far to shorten if they won't.
- **The style gives the colours.** The templates use only the agent's ink, paper and accent; the marks are tints of ink so they read in black and white, and a highlight uses the accent when it differs from the ink. Never carry a meaning in colour alone.
- **Sizes:** 1080 x 1350 (the default) or 1080 x 1080. A chart is drawn to fit its place at the size you ask for.

## Your own chart

When none of the four charts fits (several series, a map, a distribution), draw it yourself with matplotlib and hand it over as `"image": "chart.png"` in a `chart-card`: the card adds the title, subtitle, source and signature and centres your chart without enlarging it (a PNG, JPEG or WebP of at most 25 MiB, 40 megapixels and 8,192 px a side; transparency goes over the paper). The kit's `assets/hrizzup.mplstyle` is a plain matplotlib style (the kit's text font, dark ink on white, no grid, no top or right frame); its first lines show how to use it. Make the figure 928 x 742 pixels (9.28 x 7.42 inches at 100 dpi) for the tall card, or 928 x 594 for the square one, label directly, start bars at zero, and save without metadata. All the rules above still apply, including the missing glyphs: matplotlib falls back to another font for a character the kit's font lacks, so keep to plain letters and digits.

## The spec

```json
{
  "template": "chart-card",
  "title": "Where 450 sits on India's air-quality scale",
  "subtitle": "The National Air Quality Index runs from 0 to 500, in six bands",
  "chart": {"type": "scale", "unit": "AQI",
            "bands": [{"name": "Good", "from": 0, "to": 50}, "..."],
            "marker": {"value": 450, "label": "The example story's reading"}},
  "source": "Bands: ... The 450 reading is from ..."
}
```

- `bar` and `column`: `"data": [{"label": "...", "value": 12.5, "text": "optional value label"}]`, `"unit"`, `"highlight"` (a label, or up to three). Up to 12 bars or 8 columns.
- `line`: the same `data` (2 to 24 points, in order), `"unit"`, `"highlight"`, `"from_zero"` (true unless you say false).
- `scale`: `"bands"` from lowest to highest (2 to 8, each `name`, `from`, `to`), an optional `"marker"` (`value`, `label`) and `"unit"`. The bands are drawn in proportion, stacked from the lowest at the bottom.
- `stat` (a `stat-card`): `"chart": {"type": "stat", "value": "450+", "label": "...", "note": "..."}`.
- `steps-card`: `"steps": ["...", "..."]`, two to five.
- `subtitle` belongs to the `chart-card` and the `steps-card`; a `stat-card` is refused with one (put the line in its `note`).

## Good and bad, from the example story

The example story is Hrizzup's own: Delhi NCR's smog and its schools. Its sources are example addresses.

**The title**

- Bad: "Delhi air". The reader doesn't know what to look for.
- Good: "Where 450 sits on India's air-quality scale".

**The axis**

- Bad: bars for 462, 455 and 380 that start at 350, so the last looks a tenth of the first.
- Good: the same three bars from zero, each labelled with its value and unit.

**The scale**

- Bad: five bands with names made up, or "Moderate" and "Poor" merged to save room.
- Good: six bands with the names and ranges the official source prints, the reading marked once, and the source named on the image.

**The source**

- Bad: no source on the image, because the post has links.
- Good: "Bands: Central Pollution Control Board, Air Quality Portal (airquality.cpcb.gov.in). The 450 reading is from Hrizzup's example story."

**Two messages**

- Bad: one chart with the readings on the left axis and the number of schools online on the right. Two scales on one picture.
- Good: two graphics, or a stat-card for the reading and a steps-card for what changed for schools.

## Before you post

- [ ] One message, said in the title; every mark on the graphic carries it.
- [ ] Bars and columns start at zero; no 3-D, no second axis; direct labels, with units.
- [ ] Every number is in the updates or your sources; nothing forecast is shown as fact; anything unconfirmed says so.
- [ ] The source is on the image, in words, and the links are in the post's sources.
- [ ] Made-up figures say "illustrative" on the image.
- [ ] You opened the picture and read it: nothing cut off or overlapping, text readable.
- [ ] The `body` says the message plainly; the `description` says what is shown (the chart's type, its title, each value, the source).
- [ ] A PNG, JPEG or WebP under 10 MiB, 1080 x 1350 or 1080 x 1080.
