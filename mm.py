#!/usr/bin/env python3
"""Manimatic launcher.

Runs the Manimatic CLI inside its managed environment (created by
``mm.py doctor --install``). Uses only the standard library so it works with
any Python 3.10+ on Windows, macOS and Linux.

    python3 mm.py <command> [options]      # macOS / Linux
    py -3 mm.py <command> [options]        # Windows
"""
from __future__ import annotations  # must stay first: lets old Pythons reach the version check

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")


def manimatic_home() -> str:
    return os.environ.get("MANIMATIC_HOME") or os.path.join(os.path.expanduser("~"), ".manimatic")


def venv_dir() -> str:
    return os.path.join(manimatic_home(), "venv")


def venv_python() -> str | None:
    if os.name == "nt":
        p = os.path.join(venv_dir(), "Scripts", "python.exe")
    else:
        p = os.path.join(venv_dir(), "bin", "python")
    return p if os.path.exists(p) else None


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def main() -> int:
    if sys.version_info < (3, 10):
        print("Manimatic needs Python 3.10 or newer (found %s)." % sys.version.split()[0])
        return 1
    args = sys.argv[1:]
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["MANIMATIC_ROOT"] = ROOT
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    vp = venv_python()
    in_venv = _same_path(sys.prefix, venv_dir())
    # Re-run inside the managed venv when it exists (doctor runs fine without it).
    if vp and not in_venv and not os.environ.get("MANIMATIC_NO_VENV"):
        return subprocess.call([vp, "-m", "manimatic", *args], env=env)

    os.environ.update({k: env[k] for k in ("MANIMATIC_ROOT", "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONPATH")})
    sys.path.insert(0, SRC)
    from manimatic.cli import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
