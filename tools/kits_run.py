#!/usr/bin/env python3
"""Run the three image kits on the samples' inputs, both ways a creator can install them, and check every output.

    python3 tools/kits_run.py --out out [--group images|voice] [--mode uv|pip|both] [--python 3.12]

The "Kits on Linux" workflow (`.github/workflows/kits-linux.yml`) runs this on a GitHub machine, and it runs the
same on a Mac. With `--group images` (the default) it runs the three image kits (the timeline card, the meme and the
infographic); with `--group voice`, the voice and video kits (see "The voice and video group" below). For each image kit it
runs the sample's own command from the skill's folder:

- `uv`: `uv run --locked --python <version> scripts/<name>.py ...`, which uses the lock beside the script;
- `pip`: a fresh virtual environment (made by uv from the same Python, with pip in it), the script's hashed
  requirements file installed with `python -m pip install --require-hashes -r ...`, then that environment's Python.

Every output is read with `hrizzup_media` (the repository's own reader): its type, its size for its format, Hrizzup's
limits and this repository's picture budget. The outputs are kept in `<out>/uv/` and `<out>/pip/`, with
`<out>/summary.json`. Whether an output is byte for byte the committed sample is reported, never a failure: another
operating system may draw the same picture a pixel differently. Exit 0 when every run made a valid picture, 1 if any
didn't, 2 for bad arguments.

The voice and video group (`--group voice`): the Audio brief's sample script is spoken and given its still, and a short explainer
(about ten seconds, made from a small script, two cards and a two-scene plan written into the output folder) is spoken, captioned,
drawn and cut, each with `uv run --locked` and with a fresh environment and the hashed requirements (one environment for each
skill, with every requirements file of the skill's commands). The models are downloaded into a folder of their own, outside the
output (about 275 MiB; never kept). Every output is read with `hrizzup_media` (its type, Hrizzup's limits, the repository's
budgets and the size its format allows), and each command's own JSON line must say `ok`: `voice.py` measured the narration's
loudness and `captions.py` the word error rate. Exit 0 when every command made a valid output, 1 if any didn't.

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


GROUPS = ("images", "voice")
# The voice and video group's inputs for the short explainer: plain words (no names a voice may misread), so the word-error gate is
# honest, and two cards and two scenes. The narration is about ten seconds, so the video is too.
SHORT_SCRIPT = ("The air in the city turned severe on Monday.\n\n"
                "Doctors advise people with breathing problems to stay indoors, and many offices let their staff work from home.\n")
SHORT_CARDS = {"cards": [
    {"kind": "title", "kicker": "The city", "title": "The air turns severe", "subtitle": "An illustrative ten-second test"},
    {"kind": "fact", "label": "Monday", "value": "Severe", "text": "Doctors advise people with breathing problems to stay indoors."},
]}
SHORT_PLAN = {"scenes": [{"image": "01-title.png", "seconds": 4.0, "motion": "zoom-in"}, {"image": "02-fact.png", "seconds": 3.0}],
              "transition": "fade"}
SHORT_STYLE = {"signature": "Illustrative sample"}
SHORT_SECONDS = (7.0, 16.0)  # the short explainer's length must fall in this range
AUDIO_SECONDS = (50.0, 75.0)  # the Audio brief's sample is about a minute
STILL_SIZES = {"audio-brief": (1080, 1080), "explainer-video": (1080, 1920)}


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


# ---------------------------------------------------------------------------------------------
# The voice and video group
# ---------------------------------------------------------------------------------------------

def voice_steps(work):
    """The commands of the voice and video group, by skill: [(skill, [(label, script, arguments, [(output, role)])])]. Every path in
    an argument is absolute (under `work`, this mode's output folder) except the Audio brief's own sample inputs, which are relative
    to its folder, where each command runs. `role` is what `hrizzup_media` checks the output as: audio, image or video."""
    audio, video = os.path.join(work, "audio-brief"), os.path.join(work, "explainer-video")
    a = lambda name: os.path.join(audio, name)  # noqa: E731
    v = lambda name: os.path.join(video, name)  # noqa: E731
    return [
        ("audio-brief", [
            ("the Audio brief's narration", "voice.py",
             ["--script", os.path.join("examples", "script.txt"), "--out", a("narration.m4a"), "--timings", a("timings.json")],
             [(a("narration.m4a"), "audio")]),
            ("the Audio brief's still", "still.py",
             ["--title", "Delhi's air turns severe", "--subtitle", "An illustrative one-minute audio brief", "--size", "1080x1080",
              "--style", os.path.join("examples", "style.json"), "--out", a("still.png")],
             [(a("still.png"), "image")]),
        ]),
        ("explainer-video", [
            ("the short explainer's narration", "voice.py",
             ["--script", v("script.txt"), "--out", v("narration.m4a"), "--timings", v("timings.json"), "--max-seconds", "30"],
             [(v("narration.m4a"), "audio")]),
            ("its captions", "captions.py",
             ["--audio", v("narration.m4a"), "--script", v("script.txt"), "--timings", v("timings.json"), "--out", v("captions.json"),
              "--srt", v("captions.srt")], []),
            ("its cards", "cards.py", ["--cards", v("cards.json"), "--out-dir", v("cards"), "--style", v("style.json")],
             [(v(os.path.join("cards", "01-title.png")), "image"), (v(os.path.join("cards", "02-fact.png")), "image")]),
            ("its video", "edit.py",
             ["--plan", v("plan.json"), "--narration", v("narration.m4a"), "--captions", v("captions.json"), "--out", v("short.mp4"),
              "--style", v("style.json")],
             [(v("short.mp4"), "video")]),
            ("its still", "still.py",
             ["--title", "The air turns severe", "--size", "1080x1920", "--style", v("style.json"), "--out", v("still.png")],
             [(v("still.png"), "image")]),
        ]),
    ]


def write_short_inputs(folder):
    """Write the short explainer's script, cards, plan and style into `folder` (made if it isn't there). The plan names the cards
    `cards.py` draws into the `cards` folder beside it."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "script.txt"), "w", encoding="utf-8") as f:
        f.write(SHORT_SCRIPT)
    for name, document in (("cards.json", SHORT_CARDS), ("style.json", SHORT_STYLE)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2)
            f.write("\n")
    plan = {"scenes": [dict(scene, image=os.path.join("cards", scene["image"])) for scene in SHORT_PLAN["scenes"]], "transition": SHORT_PLAN["transition"]}
    with open(os.path.join(folder, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
        f.write("\n")


def check_voice_output(media, path, role, skill, label):
    """(info, problems) for one output of the voice and video group: Hrizzup's limits and this repository's budgets, the size its
    format allows, and a length that is what the sample is for."""
    try:
        info = media.inspect(path)
    except (media.MediaError, OSError) as error:
        return None, ["can't be read: %s" % error]
    found = list(media.problems(info, role))
    if role == "audio":
        low, high = AUDIO_SECONDS if skill == "audio-brief" else (6.0, 14.0)
        if not low <= info.seconds <= high:
            found.append("is %.1f s; this sample should run %.0f to %.0f s" % (info.seconds, low, high))
    elif role == "video":
        if not SHORT_SECONDS[0] <= info.seconds <= SHORT_SECONDS[1]:
            found.append("is %.1f s; the short explainer should run %.0f to %.0f s" % (info.seconds, SHORT_SECONDS[0], SHORT_SECONDS[1]))
    elif role == "image":
        want = STILL_SIZES[skill]  # the Audio brief's still is square; the explainer's cards and still are a video's frame
        if (info.width, info.height) != want:
            found.append("is %dx%d; it should be %dx%d" % (info.width, info.height, want[0], want[1]))
    return info, found


def skill_requirements(skill, steps):
    """The requirements files (relative to the skill's folder) of the commands a skill runs in this group, each once, in order."""
    found = []
    for _label, script, _arguments, _outputs in steps:
        name = os.path.join("scripts", script[:-3] + ".requirements.txt")
        if name not in found:
            found.append(name)
    return found


def last_json(text):
    """The JSON object on the last line of a command's output, or None."""
    lines = text.strip().split("\n")
    try:
        found = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def run_group_voice(args, media, log):
    """Run the voice and video group; returns (results, failed)."""
    out_root = os.path.abspath(args.out)
    models = tempfile.mkdtemp(prefix="kits-models-")  # downloaded once, shared by every command, never part of the output
    scratch = tempfile.mkdtemp(prefix="kits-venv-")
    env = dict(os.environ)
    env["HRIZZUP_MODELS_DIR"] = models
    modes = MODES if args.mode == "both" else (args.mode,)
    results, failed = [], False
    for mode in modes:
        work = os.path.join(out_root, "voice-" + mode)
        write_short_inputs(os.path.join(work, "explainer-video"))
        os.makedirs(os.path.join(work, "audio-brief"), exist_ok=True)
        for skill, steps in voice_steps(work):
            folder = os.path.join(ROOT, "skills", skill)
            interpreter, setup_problem = None, None
            if mode == "pip":
                venv = os.path.join(scratch, skill)
                interpreter = os.path.join(venv, "Scripts" if os.name == "nt" else "bin", "python")
                setup = [["uv", "venv", "--python", args.python, "--seed", venv]]
                setup += [[interpreter, "-m", "pip", "install", "--require-hashes", "--no-input", "-r", name] for name in skill_requirements(skill, steps)]
                for command in setup:
                    code, last = run(command, folder, log)
                    if code != 0:
                        setup_problem = "`%s ...` exited %d: %s" % (os.path.basename(command[0]), code, last[:300])
                        break
            for label, script, arguments, outputs in steps:
                entry = {"mode": mode, "skill": skill, "step": label, "ok": False, "problems": [], "outputs": []}
                if setup_problem:
                    entry["problems"].append(setup_problem)
                else:
                    if interpreter:
                        command = [interpreter, os.path.join("scripts", script)] + arguments
                    else:
                        command = ["uv", "run", "--locked", "--python", args.python, os.path.join("scripts", script)] + arguments
                    log("$ (in %s) %s" % (os.path.relpath(folder, ROOT), " ".join(command)))
                    done = subprocess.run(command, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=env)
                    lines = done.stdout.strip().split("\n")
                    log("\n".join(lines[-14:]))
                    said = last_json(done.stdout)
                    if done.returncode != 0 or not said or not said.get("ok"):
                        entry["problems"].append("`%s` exited %d: %s" % (script, done.returncode, (said or {}).get("problem") or lines[-1][:300]))
                    elif said.get("checks") and not all(c.get("ok") for c in said["checks"]):
                        entry["problems"].append("`%s` reported a check that failed: %s" % (script, said["checks"]))
                    else:
                        entry["checks"] = said.get("checks", [])
                    if not entry["problems"]:
                        for path, role in outputs:
                            info, found = check_voice_output(media, path, role, skill, label)
                            entry["problems"] += ["%s %s" % (os.path.relpath(path, out_root), p) for p in found]
                            if info is not None:
                                entry["outputs"].append({"path": os.path.relpath(path, out_root), "bytes": info.bytes, "width": info.width,
                                                         "height": info.height, "seconds": info.seconds})
                entry["ok"] = not entry["problems"]
                failed = failed or not entry["ok"]
                results.append(entry)
    shutil.rmtree(scratch, ignore_errors=True)
    shutil.rmtree(models, ignore_errors=True)
    return results, failed


def make_parser():
    parser = argparse.ArgumentParser(
        prog="kits_run.py",
        description="Run the timeline card, meme and infographic kits on the samples' inputs, with uv and with plain pip, and check every output.",
        epilog="Example: python3 tools/kits_run.py --out out --mode both --python 3.12")
    parser.add_argument("--out", required=True, help="the folder for the outputs and summary.json (made if it isn't there)")
    parser.add_argument("--group", choices=GROUPS, default="images", help="images (default: the timeline card, the meme and the infographic) or voice (the Audio brief and a short explainer)")
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

    if args.group == "voice":
        return finish_voice(args, media, out_root, log)
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


def finish_voice(args, media, out_root, log):
    """Run the voice and video group and write its summary; exit 0 or 1."""
    os.makedirs(out_root, exist_ok=True)
    results, failed = run_group_voice(args, media, log)
    with open(os.path.join(out_root, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"group": "voice", "python": args.python, "results": results}, f, indent=2)
        f.write("\n")
    log("")
    for entry in results:
        shown = ", ".join("%s %s bytes%s" % (o["path"], o["bytes"], " %.1f s" % o["seconds"] if o["seconds"] else "") for o in entry["outputs"])
        log("%-4s %-16s %-34s %s %s" % (entry["mode"], entry["skill"], entry["step"], "ok  " if entry["ok"] else "FAIL", "; ".join(entry["problems"]) or shown))
    log("failed" if failed else "every voice and video kit made valid outputs")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
