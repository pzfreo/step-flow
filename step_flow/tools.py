"""The released command-line tools step-flow calls, and the pins it checks them against."""

import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = ("specify-core", "draftwright")
LOCK = Path(__file__).resolve().parent.parent / "tools.lock"


class ToolError(Exception):
    """A tool could not be found, is not the pinned version, or failed in a way no stage expects."""


def pins(lock=LOCK):
    """``{package: version}`` from tools.lock (``name==version`` lines; ``#`` comments)."""
    out = {}
    for line in Path(lock).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, _, version = line.partition("==")
            out[name.strip()] = version.strip()
    return out


def executable(name):
    """The tool beside this Python (the pinned venv) first, then PATH."""
    here = Path(sys.executable).parent / name
    if here.exists():
        return str(here)
    found = shutil.which(name)
    if not found:
        raise ToolError(f"{name} not found beside {sys.executable} or on PATH")
    return found


def installed_version(name):
    """The version of the package that provides ``name`` in this Python, or None."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def check_versions(allow_unpinned=False):
    """``{tool: {"path", "version", "pinned"}}``; raises ToolError on a mismatch unless allowed."""
    wanted = pins()
    report, bad = {}, []
    for name in TOOLS:
        path = executable(name)
        in_venv = Path(path).parent == Path(sys.executable).parent
        version = installed_version(name) if in_venv else None
        report[name] = {"path": path, "version": version, "pinned": wanted.get(name)}
        if version != wanted.get(name):
            bad.append(f"{name} {version or 'unknown (not in this venv)'} at {path}, pinned {wanted.get(name)}")
    if bad and not allow_unpinned:
        raise ToolError("tool versions do not match tools.lock: " + "; ".join(bad))
    return report


class Runner:
    """Runs tool commands and keeps a log of every command, its exit code and stderr."""

    def __init__(self):
        self.log = []

    def run(self, name, *args, stdout_to=None):
        cmd = [executable(name), *map(str, args)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if stdout_to is not None:
            Path(stdout_to).write_text(proc.stdout)
        self.log.append({"cmd": [name, *map(str, args)], "rc": proc.returncode,
                         "stderr": proc.stderr.strip()[-2000:]})
        return proc


def load_json(path):
    with open(path) as f:
        return json.load(f)


def dump_json(data, path):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
