# Notices

Everything this repository ships, or asks a creator to install, with its licence. `tools/catalogue.py check` fails a pull request that adds a package, a font, a model or a tool without a row here, with a licence and the version it uses.

- **Packages:** one row for every package in every script's lock file (a script's own packages and everything they pull in), at the version locked.
- **Fonts:** one row for each font family, with its `OFL.txt` beside the font files.
- **Models and FFmpeg:** one row for each model a script downloads, and for the FFmpeg program and libraries a package ships.
- **GPL:** a row whose licence is GPL (not LGPL) says "installed by the creator's setup", never "bundled": nothing GPL is copied into this repository. It installs on the creator's machine and runs as a separate program, or is imported only by `voice.py`.

| Name | Version | Licence | Home | How it's used | Used by |
|---|---|---|---|---|---|
