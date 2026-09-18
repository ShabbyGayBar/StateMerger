"""Headless-safe CLI and GUI boundary tests."""

import sys

import pytest

from vic3_state_merger import cli, gui

pytestmark = pytest.mark.smoke


def test_cli_parser_and_version(capsys):
    parser = cli.get_parser()
    args = parser.parse_args(["plan.json", "/game", "/mod", "--ignore-small-states"])
    assert args.merge_file == "plan.json"
    assert args.ignore_small_states is True
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    assert "state-merger" in capsys.readouterr().out


@pytest.mark.parametrize(
    "values",
    [
        (("", "/game", "/mod", "4"), "Merge file is required."),
        (("plan", "", "/mod", "4"), "Game root is required."),
        (("plan", "/game", "", "4"), "Mod output folder is required."),
        (("plan", "/game", "/mod", "x"), "Small state limit must be an integer."),
        (("plan", "/game", "/mod", "-1"), "Small state limit must be >= 0."),
    ],
)
def test_gui_input_validation(values):
    args, message = values
    valid, actual = gui._validate_inputs(*args)
    assert valid is False
    assert actual == message


def test_gui_valid_input():
    assert gui._validate_inputs("plan", "/game", "/mod", "0") == (True, "")


def test_cli_main_dispatch(monkeypatch):
    called = {}

    def fake_run_merge(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(cli, "run_merge", fake_run_merge)
    monkeypatch.setattr(
        sys,
        "argv",
        ["state-merger-cli", "plan.json", "/game", "/mod", "--small-state-limit", "2"],
    )
    cli.main()
    assert called["merge_file"] == "plan.json"
    assert called["small_state_limit"] == 2
