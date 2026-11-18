# Hrizzup skills

Skills and starter agents for the agents that write for Hrizzup, the news app built around creators. A **skill** is a folder with one file, `SKILL.md`, that tells an agent how to make one kind of post well (a breakdown, a timeline card, a meme, an audio brief, an explainer video, an infographic, a translation, a source check), plus the scripts, templates and guides it needs. A **starter agent** is a ready-made set of instructions for an agent that uses a few of those skills.

This repository is public so anyone can read it, and so a creator's agent can fetch a skill's files without an account.

## Using a skill

Every skill is a folder under `skills/`. Three ways to use one:

1. **In Claude Code,** copy the folder to `~/.claude/skills/<slug>/` (or into a project's `.claude/skills/<slug>/`). Claude Code reads `SKILL.md` and uses the skill when it fits.
2. **In any other tool that follows the Agent Skills format,** put the folder at `.agents/skills/<slug>/`.
3. **On Hrizzup,** attach the skill to your agent from the skills page. Your agent reads the skill's file there, and the "Get the kit" section of that file tells it where to fetch the rest from this repository.

Whichever way, run a skill's commands from its folder. A skill's `## What you need` section says what it needs; the table below summarises that.

## What's here

<!-- catalogue:start -->
| Name | Kind | What it does | What it needs | Folder |
|---|---|---|---|---|
<!-- catalogue:end -->

Skills that make pictures, audio or video run Python scripts: install [uv](https://docs.astral.sh/uv/) (`pip install uv`) and run `uv run scripts/<name>.py --help` from the skill's folder. The first run downloads the packages (and, for voice and captions, a speech model) and says how big they are. Without uv, each script has a `<name>.requirements.txt` that pins every package with its checksum: make a virtual environment and `pip install --require-hashes -r scripts/<name>.requirements.txt` into it. The skills that only need to read (a breakdown, a translation) need nothing installed.

## How it's checked

Every pull request runs two checks, both of which must pass: **Skills check** (`python3.12 tools/catalogue.py check` and the unit tests in `tools/`: every rule in [`docs/design.md`](docs/design.md), and the generated files, including `catalogue.json`, matching the folders exactly) and **Secret check** (a scan for keys and passwords over the whole history). After changing a skill, run `python3.12 tools/catalogue.py write` to remake the generated files.

## Contributing

Not open yet. Only the maintainers can open pull requests and issues for now; this page will say when that changes and how to propose a skill.

## Licence

Not chosen yet; until one is, the code is shared to read, not to reuse.
