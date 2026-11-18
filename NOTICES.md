# Notices

Everything this repository ships, or asks a creator to install, with its licence. `tools/catalogue.py check` fails a pull request that adds a package, a font, a model or a tool without a row here, with a licence and the version it uses.

- **Packages:** one row for every package in every script's lock file (a script's own packages and everything they pull in), at the version locked.
- **Fonts:** one row for each font family, with its `OFL.txt` beside the font files.
- **Models and FFmpeg:** one row for each model a script downloads, and for the FFmpeg program and libraries a package ships.
- **GPL:** a row whose licence is GPL (not LGPL) says "installed by the creator's setup", never "bundled": nothing GPL is copied into this repository. It installs on the creator's machine and runs as a separate program, or is imported only by `voice.py`.

| Name | Version | Licence | Home | How it's used | Used by |
|---|---|---|---|---|---|
| pillow | 13.0.0 | MIT-CMU | https://python-pillow.org | Draws the timeline card's picture and text; imported by `hrizzup_draw.py` | `timeline_card.py` |
| fonttools | 4.68.0 | MIT | https://github.com/fonttools/fonttools | Reads which characters a font can draw, so text a font lacks is refused | `timeline_card.py` |
| Anton | Regular, from google/fonts at commit cc39c4c2c304bc368c9b7c311ea2bcc6013299fe | SIL Open Font License 1.1 | https://github.com/googlefonts/AntonFont | The display font of the shared drawing module; copied into a skill's `assets/fonts` when the skill uses it (its licence beside it) | `hrizzup_draw.py` (no skill holds it yet) |
| Atkinson Hyperlegible | Regular and Bold, from google/fonts at commit cc39c4c2c304bc368c9b7c311ea2bcc6013299fe | SIL Open Font License 1.1 | https://github.com/googlefonts/atkinson-hyperlegible | The text font of every card and picture; copied into the skills that draw, its licence beside it | `timeline_card.py` through `hrizzup_draw.py` |
