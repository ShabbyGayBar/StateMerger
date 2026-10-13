# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run the delivered wheel and executable outside the development checkout."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def clean_environment():
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    return env


def validate_exe(executable, version, timeout=60):
    with tempfile.TemporaryDirectory(prefix="state-merger-exe-") as directory:
        report = Path(directory) / "startup.json"
        process = subprocess.Popen(
            [str(executable.resolve()), "--smoke-test", str(report)],
            cwd=directory,
            env=clean_environment(),
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
            else:
                process.kill()
            process.wait(timeout=10)
            raise RuntimeError("Packaged GUI startup timed out") from None
        if code != 0 or not report.is_file():
            raise RuntimeError("Packaged GUI failed or did not write a startup report")
        if json.loads(report.read_text(encoding="utf-8")) != {
            "status": "ok",
            "version": version,
        }:
            raise RuntimeError("Packaged GUI reported an incorrect version or status")


def validate_wheel(wheel, version, fixture):
    with tempfile.TemporaryDirectory(prefix="state-merger-wheel-") as directory:
        work = Path(directory)
        venv = work / "venv"
        env = clean_environment()

        def run(*command):
            subprocess.run(command, cwd=work, env=env, check=True, timeout=300)

        run("uv", "venv", "--python", "3.14", str(venv))
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = venv / (
            "Scripts/state-merger-cli.exe"
            if os.name == "nt"
            else "bin/state-merger-cli"
        )
        run("uv", "pip", "install", "--python", str(python), str(wheel.resolve()))
        shutil.copytree(fixture, work / "micro_game")
        script = Path(__file__).with_name("validate_installed.py")
        shutil.copyfile(script, work / script.name)
        run(str(python), "-I", str(work / script.name), str(cli), version, str(venv))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("exe", "wheel"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    info = json.loads(
        (args.bundle / "release-manifest.json").read_text(encoding="utf-8")
    )
    version = info["version"]
    if args.kind == "exe":
        validate_exe(args.bundle / "state-merger.exe", version)
    else:
        if args.fixture is None:
            parser.error("--fixture is required for wheel validation")
        validate_wheel(
            args.bundle / f"vic3_state_merger-{version}-py3-none-any.whl",
            version,
            args.fixture,
        )


if __name__ == "__main__":
    main()
