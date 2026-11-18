#!/usr/bin/env python3
"""Run the three image kits on the samples' inputs, both ways a creator can install them, and check every output.

    python3 tools/kits_run.py --out out [--mode uv|pip|both] [--python 3.12]

The "Kits on Linux" workflow (`.github/workflows/kits-linux.yml`) runs this on a GitHub machine, and it runs the
same on a Mac. For each kit (the timeline card, the meme and the infographic) it runs the sample's own command from
the skill's folder:

- `uv`: `uv run --locked --python <version> scripts/<name>.py ...`, which uses the lock beside the script;
- `pip`: a fresh virtual environment (made by uv from the same Python, with pip in it), the script's hashed
  requirements file installed with `python -m pip install --require-hashes -r ...`, then that environment's Python.

Every output is read with `hrizzup_media` (the repository's own reader): its type, its size for its format, Hrizzup's
limits and this repository's picture budget. The outputs are kept in `<out>/uv/` and `<out>/pip/`, with
`<out>/summary.json`. Whether an output is byte for byte the committed sample is reported, never a failure: another
operating system may draw the same picture a pixel differently. Exit 0 when every run made a valid picture, 1 if any
didn't, 2 for bad arguments.

Standard library only; it runs under the same Python as `catalogue.py` and parses as Python 3.9.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMELINE_TITLE = "Delhi NCR's air turns 'severe' as pollution readings pass 450 and primary schools move online"
MEME_TEXT = ("Monday's update: schools across Delhi NCR go online. Tuesday's correction: only Delhi's primary schools. "
             "Noida and Gurugram stay open.")
MEME_TEXT2 = "The laptop only fit on one roof"
# What each kit makes: (skill, script, arguments after the script name, output file name, the sample it should match
# (inside the skill's examples/), the sizes its format allows)
KITS = (
    ("timeline", "timeline_card.py",
     ["--items", "examples/updates.json", "--title", TIMELINE_TITLE, "--style", "examples/style.json"],
     "card.png", "card.png", ((1080, 1350), (1080, 1080))),
    ("meme", "meme.py",
     ["--template", "two-panel", "--image", "examples/picture.png", "--text", MEME_TEXT, "--text2", MEME_TEXT2,
      "--size", "1080x1350", "--style", "examples/style.json"],
     "meme.png", "meme.png", ((1080, 1080), (1080, 1350))),
    ("infographic", "infographic.py",
     ["--spec", "examples/spec.json", "--size", "1080x1350", "--style", "examples/style.json"],
     "infographic.png", "infographic.png", ((1080, 1350), (1080, 1080))),
)
MODES = ("uv", "pip")
# What the pip way also asks the environment it installed, so NOTICES.md's libimagequant row can be confirmed on each
# platform: whether Pillow's wheel was built with it (Pillow lists it as optional; the macOS arm64 wheel wasn't).
FEATURE_CODE = ("import json; from PIL import features; "
                "print(json.dumps({'libimagequant': features.check_feature('libimagequant'), 'version': features.version('libimagequant')}))")


def load_media():
    """The repository's own reader, from shared/scripts (the same file `catalogue.py` loads)."""
    path = os.path.join(ROOT, "shared", "scripts", "hrizzup_media.py")
    spec = importlib.util.spec_from_file_location("hrizzup_media", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hrizzup_media"] = module
    spec.loader.exec_module(module)
    return module


def uv_command(python, script, arguments, out):
    """The command that runs a script through uv's lock, from the skill's folder."""
    return ["uv", "run", "--locked", "--python", python, os.path.join("scripts", script)] + arguments + ["--out", out]


def pip_commands(python, script, arguments, out, venv):
    """The commands for the no-uv path: a fresh environment with pip, the hashed requirements, then the script."""
    requirements = os.path.join("scripts", script[:-3] + ".requirements.txt")
    interpreter = os.path.join(venv, "Scripts" if os.name == "nt" else "bin", "python")
    return [
        ["uv", "venv", "--python", python, "--seed", venv],
        [interpreter, "-m", "pip", "install", "--require-hashes", "--no-input", "-r", requirements],
        [interpreter, os.path.join("scripts", script)] + arguments + ["--out", out],
    ]


def feature_command(interpreter):
    """The command that asks Pillow, in the environment the pip way made, whether its wheel has libimagequant."""
    return [interpreter, "-c", FEATURE_CODE]


def run(command, folder, log):
    """Run a command in `folder`, keeping its output; returns (exit code, the last lines it printed)."""
    log("$ (in %s) %s" % (os.path.relpath(folder, ROOT), " ".join(command)))
    done = subprocess.run(command, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    lines = done.stdout.strip().split("\n")
    log("\n".join(lines[-12:]))
    return done.returncode, lines[-1] if lines else ""


def check_output(media, path, sizes):
    """Problems with one output (an empty list when it is a valid picture of an allowed size)."""
    try:
        info = media.inspect(path)
    except (media.MediaError, OSError) as error:
        return None, ["can't be read: %s" % error]
    found = list(media.problems(info, "image"))
    if (info.width, info.height) not in sizes:
        found.append("is %dx%d; its format allows %s" % (info.width, info.height, " or ".join("%dx%d" % s for s in sizes)))
    return info, found


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_parser():
    parser = argparse.ArgumentParser(
        prog="kits_run.py",
        description="Run the timeline card, meme and infographic kits on the samples' inputs, with uv and with plain pip, and check every output.",
        epilog="Example: python3 tools/kits_run.py --out out --mode both --python 3.12")
    parser.add_argument("--out", required=True, help="the folder for the outputs and summary.json (made if it isn't there)")
    parser.add_argument("--mode", choices=MODES + ("both",), default="both", help="uv, pip, or both (default)")
    parser.add_argument("--python", default="3.12", help="the Python version for both ways (default 3.12)")
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    out_root = os.path.abspath(args.out)
    modes = MODES if args.mode == "both" else (args.mode,)
    media = load_media()

    def log(text):
        print(text, flush=True)

    scratch = tempfile.mkdtemp(prefix="kits-venv-")  # the pip way's environments: not in the folder that is kept
    results, failed = [], False
    for mode in modes:
        folder = os.path.join(out_root, mode)
        os.makedirs(folder, exist_ok=True)
        for skill, script, arguments, name, sample, sizes in KITS:
            skill_folder = os.path.join(ROOT, "skills", skill)
            target = os.path.join(folder, name)
            entry = {"mode": mode, "kit": skill, "output": os.path.relpath(target, out_root), "ok": False, "problems": []}
            if mode == "uv":
                commands = [uv_command(args.python, script, arguments, target)]
            else:
                venv = os.path.join(scratch, skill)  # a fresh environment for each kit
                commands = pip_commands(args.python, script, arguments, target, venv)
            code, last = 0, ""
            for command in commands:
                code, last = run(command, skill_folder, log)
                if code != 0:
                    entry["problems"].append("`%s ...` exited %d: %s" % (os.path.basename(command[0]), code, last[:300]))
                    break
            if code == 0 and mode == "pip":
                asked, said = run(feature_command(commands[-1][0]), skill_folder, log)
                try:
                    entry["pillowFeatures"] = json.loads(said)
                    log("Pillow's libimagequant here: %s" % entry["pillowFeatures"]["libimagequant"])
                except ValueError:
                    entry["pillowFeatures"] = None
                    log("Pillow's libimagequant here: couldn't be read (%s)" % said[:120])
            if code == 0:
                info, found = check_output(media, target, sizes)
                entry["problems"] += found
                if info is not None:
                    entry.update({"bytes": info.bytes, "width": info.width, "height": info.height})
                    committed = os.path.join(skill_folder, "examples", sample)
                    if os.path.isfile(committed):
                        entry["sameAsCommittedSample"] = digest(target) == digest(committed)
            entry["ok"] = not entry["problems"]
            failed = failed or not entry["ok"]
            results.append(entry)
    shutil.rmtree(scratch, ignore_errors=True)
    with open(os.path.join(out_root, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"python": args.python, "results": results}, f, indent=2)
        f.write("\n")
    log("")
    for entry in results:
        features = entry.get("pillowFeatures")
        if features:
            log("     %s: libimagequant in Pillow's wheel: %s" % (entry["kit"], features["libimagequant"]))
        log("%-4s %-12s %s %s %s" % (entry["mode"], entry["kit"], "ok  " if entry["ok"] else "FAIL",
                                      "%sx%s, %s bytes" % (entry.get("width"), entry.get("height"), entry.get("bytes")) if "bytes" in entry else "",
                                      "; ".join(entry["problems"]) or ("(same bytes as the committed sample)" if entry.get("sameAsCommittedSample") else "(a different drawing from the committed sample's bytes)")))
    log("failed" if failed else "every kit made a valid picture")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
