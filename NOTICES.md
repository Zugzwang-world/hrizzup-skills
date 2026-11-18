# Notices

Everything this repository ships, or asks a creator to install, with its licence. `tools/catalogue.py check` fails a pull request that adds a package, a font, a model or a tool without a row here, with a licence and the version it uses.

- **Packages:** one row for every package in every script's lock file (a script's own packages and everything they pull in), at the version locked.
- **Fonts:** one row for each font family, with its `OFL.txt` beside the font files.
- **Models and FFmpeg:** one row for each model a script downloads, and for the FFmpeg program and libraries a package ships.
- **GPL:** a row whose licence is GPL (not LGPL) says "installed by the creator's setup", never "bundled": nothing GPL is copied into this repository. It installs on the creator's machine and runs as a separate program, or is imported only by `voice.py`.

| Name | Version | Licence | Home | How it's used | Used by |
|---|---|---|---|---|---|
| pillow | 13.0.0 | MIT-CMU | https://python-pillow.org | Draws the cards' pictures and text, and places the infographic's chart; imported by `hrizzup_draw.py` | `timeline_card.py`, `meme.py`, `infographic.py` |
| fonttools | 4.68.0 | MIT | https://github.com/fonttools/fonttools | Reads which characters a font can draw, so text a font lacks is refused (matplotlib needs it too) | `timeline_card.py`, `meme.py`, `infographic.py` |
| matplotlib | 3.11.2 | Matplotlib licence (PSF-based) | https://matplotlib.org | Draws the infographic's bars, columns, lines and scales on its Agg canvas, with the kit's fonts | `infographic.py` |
| numpy | 2.5.4 | BSD-3-Clause (with 0BSD, MIT, Zlib and CC0-1.0 parts) | https://numpy.org | Arrays under matplotlib; pinned directly so a later release can't move it | `infographic.py` |
| contourpy | 1.4.0 | BSD-3-Clause | https://github.com/contourpy/contourpy | Contour calculations inside matplotlib; the infographic doesn't call it | `infographic.py` through matplotlib |
| cycler | 0.12.1 | BSD-3-Clause | https://github.com/matplotlib/cycler | Style cycles inside matplotlib | `infographic.py` through matplotlib |
| kiwisolver | 1.5.1 | BSD-3-Clause | https://github.com/nucleic/kiwi | Layout solver inside matplotlib | `infographic.py` through matplotlib |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging | Version handling inside matplotlib | `infographic.py` through matplotlib |
| pyparsing | 3.3.3 | MIT | https://github.com/pyparsing/pyparsing | Reads matplotlib's text markup | `infographic.py` through matplotlib |
| python-dateutil | 4.0.0 | BSD-3-Clause | https://github.com/dateutil/dateutil | Date handling inside matplotlib | `infographic.py` through matplotlib |
| tzdata | 2026.6 | Apache-2.0 | https://github.com/python/tzdata | Time zone data pulled in by python-dateutil (the data itself is public domain) | `infographic.py` through python-dateutil |
| OpenBLAS | the build inside numpy 2.5.4's wheel | BSD-3-Clause | https://github.com/OpenMathLib/OpenBLAS | The linear-algebra library compiled into numpy's wheel (`libscipy_openblas`); installed by the creator's setup with numpy, never copied here, and the infographic never calls it | `infographic.py` through numpy |
| LAPACK | the build inside numpy 2.5.4's wheel | BSD-3-Clause-Open-MPI | https://www.netlib.org/lapack/ | Linear algebra routines inside the same OpenBLAS library; installed by the creator's setup with numpy, never copied here | `infographic.py` through numpy |
| GCC runtime library (libgfortran, libgcc) | the build inside numpy 2.5.4's wheel | GPL-3.0-or-later WITH GCC-exception-3.1 | https://gcc.gnu.org/onlinedocs/gcc/Libgcc.html | The compiler's runtime libraries that numpy's wheel carries for its compiled code; the GCC Runtime Library Exception lets other programs use them; installed by the creator's setup with numpy, never copied here, and run only as part of numpy | `infographic.py` through numpy |
| libquadmath | the build inside numpy 2.5.4's wheel | LGPL-2.1-or-later | https://gcc.gnu.org/onlinedocs/libquadmath/ | Quad-precision maths that numpy's wheel carries for its compiled code; installed by the creator's setup with numpy, never copied here | `infographic.py` through numpy |
| DejaVu fonts | the files inside matplotlib 3.11.2's wheel | Bitstream Vera licence, with the DejaVu changes in the public domain | https://dejavu-fonts.github.io/ | matplotlib's own default font, in its wheel (`mpl-data/fonts/ttf`); installed by the creator's setup with matplotlib, never copied here. The infographic draws every chart text in Atkinson Hyperlegible or Anton from this kit, never in these | `infographic.py` through matplotlib |
| STIX fonts | the files inside matplotlib 3.11.2's wheel | SIL Open Font License 1.1 | https://github.com/stipub/stixfonts | matplotlib's maths fonts, in its wheel (`mpl-data/fonts/ttf`); installed by the creator's setup with matplotlib, never copied here; the infographic switches maths text off, so it never draws with them | `infographic.py` through matplotlib |
| Anton | Regular, from google/fonts at commit cc39c4c2c304bc368c9b7c311ea2bcc6013299fe | SIL Open Font License 1.1 | https://github.com/googlefonts/AntonFont | The display font of the shared drawing module; copied into a skill's `assets/fonts` when the skill uses it (its licence beside it) | `meme.py` and `infographic.py` through `hrizzup_draw.py` |
| Atkinson Hyperlegible | Regular and Bold, from google/fonts at commit cc39c4c2c304bc368c9b7c311ea2bcc6013299fe | SIL Open Font License 1.1 | https://github.com/googlefonts/atkinson-hyperlegible | The text font of every card and picture; copied into the skills that draw, its licence beside it | `timeline_card.py`, `meme.py` and `infographic.py` through `hrizzup_draw.py` |
