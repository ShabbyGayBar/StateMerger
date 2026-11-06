# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Application diagnostics must not break merges on legacy Windows streams."""

import io
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_installed import run_cli
from vic3_state_merger import cli, gui
from vic3_state_merger.logging_config import configure_logging

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("application_logging")]
FIXTURE = Path(__file__).parent / "fixtures" / "micro_game"


def test_import_does_not_configure_application_logging():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import logging
root = logging.getLogger()
before = (root.handlers[:], root.level)
import vic3_state_merger
logger = logging.getLogger('vic3_state_merger')
assert all(isinstance(h, logging.NullHandler) for h in logger.handlers)
assert logger.level == logging.NOTSET and logger.propagate
assert (root.handlers, root.level) == before
""",
        ],
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_levels_utf8_and_root_isolation(tmp_path, capsys, application_logging):
    root = logging.getLogger()
    before = root.handlers[:], root.level
    path = tmp_path / "logs" / "merge.log"
    configure_logging(log_file=path)
    logger = logging.getLogger("vic3_state_merger.states")
    logger.debug("hidden detail")
    logger.info("Progress: %s", "贝塔港")
    logger.warning("Unknown resource")
    output = capsys.readouterr()
    assert output.out == ""
    assert "hidden detail" not in output.err
    assert "INFO vic3_state_merger.states: Progress: 贝塔港" in output.err
    assert "WARNING" in output.err
    assert "贝塔港" in path.read_text(encoding="utf-8")
    assert "hidden detail" not in path.read_text(encoding="utf-8")
    assert (root.handlers, root.level) == before


def test_reconfiguration_closes_owned_handlers_only(tmp_path, application_logging):
    external = logging.NullHandler()
    application_logging.addHandler(external)
    configure_logging("DEBUG", log_file=tmp_path / "first.log", console=False)
    file_handler = next(
        h for h in application_logging.handlers if hasattr(h, "baseFilename")
    )
    configure_logging("DEBUG", log_file=tmp_path / "second.log", console=False)
    assert file_handler.stream is None
    assert external in application_logging.handlers
    application_logging.debug("exactly once")
    assert (tmp_path / "first.log").read_text() == ""
    assert (tmp_path / "second.log").read_text().count("exactly once") == 1


def test_rotation_preserves_utf8(tmp_path, application_logging):
    path = tmp_path / "merge.log"
    configure_logging("DEBUG", log_file=path, console=False)
    handler = next(h for h in application_logging.handlers if hasattr(h, "maxBytes"))
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3
    handler.maxBytes = 160
    for index in range(12):
        application_logging.debug("%s %s", index, "贝塔港" * 10)
    assert path.with_suffix(".log.1").exists()
    assert path.with_suffix(".log.3").exists()
    assert not path.with_suffix(".log.4").exists()
    assert "贝塔港" in path.read_text(encoding="utf-8")
    for backup in tmp_path.glob("merge.log.*"):
        assert "贝塔港" in backup.read_text(encoding="utf-8")


def test_strict_cp1252_console_escapes_messages_and_tracebacks(
    monkeypatch, tmp_path, application_logging
):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stderr", stream)
    path = tmp_path / "merge.log"
    configure_logging("DEBUG", log_file=path)
    application_logging.debug("Inherited %s café", "贝塔港")
    try:
        raise ValueError("贝塔港")
    except ValueError:
        application_logging.exception("Failed %s", "贝塔港")
    output = raw.getvalue().decode("cp1252")
    assert r"\u8d1d\u5854\u6e2f" in output
    assert "café" in output
    assert "Traceback" in output and "ValueError:" in output
    assert "--- Logging error ---" not in output
    assert "贝塔港" in path.read_text(encoding="utf-8")


def test_missing_stderr(monkeypatch, application_logging):
    monkeypatch.setattr(sys, "stderr", None)
    configure_logging()
    application_logging.warning("No console available")


def test_failed_file_setup_preserves_console(tmp_path, capsys, application_logging):
    configure_logging()
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    with pytest.raises(OSError):
        configure_logging(log_file=blocked / "merge.log")
    application_logging.error("Setup failed")
    assert "Setup failed" in capsys.readouterr().err


def test_cli_logging_options():
    args = cli.get_parser().parse_args(
        ["plan", "game", "mod", "--log-level", "DEBUG", "--log-file", "run.log"]
    )
    assert args.log_level == "DEBUG" and args.log_file == "run.log"
    defaults = cli.get_parser().parse_args(["plan", "game", "mod"])
    assert defaults.log_level == "INFO" and defaults.log_file is None
    with pytest.raises(SystemExit):
        cli.get_parser().parse_args(["plan", "game", "mod", "--log-level", "invalid"])


@pytest.mark.parametrize("setup_failure", [False, True])
@pytest.mark.parametrize("level", ["INFO", "CRITICAL"])
def test_cli_failure_reports_traceback(
    monkeypatch, tmp_path, capsys, setup_failure, level
):
    def fail(**kwargs):
        raise ValueError("贝塔港")

    args = ["state-merger-cli", "plan", "game", "mod", "--log-level", level]
    if setup_failure:
        blocked = tmp_path / "blocked"
        blocked.write_text("file")
        args += ["--log-file", str(blocked / "merge.log")]
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(cli, "run_merge", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "Traceback" in output.err
    assert "Merge or logging setup failed" in output.err


def test_gui_file_logging_without_console(tmp_path, capsys, application_logging):
    path = gui._configure_merge_logging(str(tmp_path / "日志" / "custom.log"))
    assert path is not None
    assert path == tmp_path / "日志" / "custom.log"
    application_logging.debug("贝塔港")
    assert "贝塔港" in path.read_text(encoding="utf-8")
    assert capsys.readouterr() == ("", "")
    assert "state-merger.log" in gui._build_help_text()


def test_gui_log_setup_failure(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    with pytest.raises(OSError):
        gui._configure_merge_logging(str(blocked / "run.log"))


def test_gui_disabled_logging_stops_previous_file(tmp_path, application_logging):
    assert gui._configure_merge_logging(None) is None
    application_logging.debug("No log requested")
    assert list(tmp_path.iterdir()) == []
    path = tmp_path / "run.log"
    gui._configure_merge_logging(str(path))
    application_logging.debug("First run")
    original = path.read_bytes()
    gui._configure_merge_logging(None)
    application_logging.debug("Logging disabled")
    assert path.read_bytes() == original
    gui._configure_merge_logging(str(path))
    application_logging.debug("Another run")
    assert path.read_bytes().startswith(original)
    assert "Another run" in path.read_text()


def test_gui_failed_destination_does_not_use_previous_log(
    tmp_path, application_logging
):
    path = tmp_path / "previous.log"
    gui._configure_merge_logging(str(path))
    with pytest.raises(OSError):
        gui._configure_merge_logging(str(path / "invalid.log"))
    application_logging.error("Setup failed")
    assert path.read_bytes() == b""


@pytest.mark.integration
@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
def test_cli_micro_game_strict_cp1252(tmp_path, level):
    game = tmp_path / "游戏"
    shutil.copytree(FIXTURE, game)
    output = tmp_path / "模组"
    log = tmp_path / "日志" / "run.log"
    env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict", "PYTHONUTF8": "0"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vic3_state_merger",
            str(game / "merge_states.json"),
            str(game),
            str(output),
            "--data-dir",
            str(tmp_path / "缓存"),
            "--log-level",
            level,
            "--log-file",
            str(log),
        ],
        capture_output=True,
        check=False,
        env=env,
        timeout=60,
    )
    stderr = result.stderr.decode("cp1252")
    assert result.returncode == 0, stderr
    assert result.stdout == b""
    assert "Merge completed" in stderr and "Processing localization" in stderr
    assert "--- Logging error ---" not in stderr
    text = log.read_text(encoding="utf-8")
    assert "游戏" in text
    if level == "DEBUG":
        assert "Inherited localization" in stderr
        assert r"\u8d1d\u5854\u6e2f" in stderr
        assert "贝塔港" in text
    else:
        assert "Inherited localization" not in stderr
    localization = (
        output / "localization/simp_chinese/hub_names_states_merging_l_simp_chinese.yml"
    )
    assert "贝塔港" in localization.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("failure", [False, True])
def test_validator_subprocess_encoding_and_failure_details(monkeypatch, failure):
    def run(command, **kwargs):
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
        assert kwargs["timeout"] == 60
        return subprocess.CompletedProcess(
            command, 7 if failure else 0, "progress 贝塔港", "failure details"
        )

    monkeypatch.setattr(subprocess, "run", run)
    if failure:
        with pytest.raises(RuntimeError, match="exit code 7") as exc:
            run_cli("cli", "plan")
        assert "stdout:\nprogress 贝塔港" in str(exc.value)
        assert "stderr:\nfailure details" in str(exc.value)
    else:
        assert run_cli("cli", "--help") == "progress 贝塔港"


@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
@pytest.mark.parametrize("blocking", [False, True])
def test_spline_diagnostics_use_configured_console_and_file(
    tmp_path, capsys, level, blocking
):
    from tests.test_spline_validation import land_case
    from vic3_state_merger.splines import merge_spline_network

    path = tmp_path / "诊断.log"
    configure_logging(level, log_file=path)
    args = land_case([(100, 101, 1, ())] if blocking else [(100, 200, 1, ())])
    args[1]["贝塔港"] = args[1].pop("A")
    args[-1] = args[-1].__class__(required={("B", "贝塔港"): [{"kind": "land"}]})
    result = merge_spline_network(*args)
    assert result.status == ("draft" if blocking else "complete")
    console = capsys.readouterr().err
    saved = path.read_text(encoding="utf-8")
    for output in (console, saved):
        if blocking:
            assert "ERROR vic3_state_merger.splines.validation" in output
            assert "unconnected_state (game_rule)" in output
            assert "missing_state_connection (advisory)" in output
        else:
            assert "WARNING vic3_state_merger.splines.validation" in output
            assert "disconnected_state_hubs (advisory)" in output
            assert "ERROR vic3_state_merger.splines.validation" not in output
        assert "贝塔港" in output
        assert ("route:" in output) == (level == "DEBUG")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["诊断.log"]
