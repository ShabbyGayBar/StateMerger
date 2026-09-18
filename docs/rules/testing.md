# Testing and Compatibility Validation

These rules define how StateMerger is tested. Automated validation, installed-game
compatibility checks, and manual in-game playtesting are separate forms of evidence.
Passing one must not be reported as passing the others.

## Test strategy

The committed synthetic micro-game is the authoritative automated test input. It is
small, original, deterministic, and mirrors the Victoria 3 directory layout without
redistributing game files.

Tests use these markers:

- `unit`: isolated model and helper behavior;
- `integration`: multi-component and full-pipeline behavior using the micro-game;
- `smoke`: lightweight CLI, GUI-helper, import, and entry-point checks;
- `live`: optional checks that require a locally installed copy of Victoria 3.

Production changes must normally include tests at the lowest useful level. Use unit
tests for merge rules and edge cases, then add an integration regression when a bug
crosses parsing, orchestration, serialization, or filesystem boundaries.

## Required local checks

Install the locked development environment:

```sh
uv sync --locked --group dev
```

Run the checks required by CI:

```sh
uv run --locked pytest -m "not live"
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
uv run --locked python -c "import vic3_state_merger; from vic3_state_merger.cli import get_parser; assert get_parser().prog == 'state-merger'"
```

The pytest configuration measures branch coverage for the core package and requires
at least 75%. Static bundled assets, `__main__.py`, and the Tkinter GUI module are
outside that core coverage calculation. GUI validation and help helpers are still
tested without starting a graphical event loop.

Pyright is currently informational. Its existing dependency-resolution and typing
diagnostics do not block CI and must not be described as a passing required check.

## Unit-test expectations

Core tests cover the behavior of:

- buildings and ownership aggregation;
- populations, state history, and trade merging;
- state-region resources, hubs, traits, sea nodes, and small-state handling;
- map-object removal and retargeting;
- keyword replacement and compound-identifier protection;
- localization cleanup, filesystem helpers, parsing, and UTF-8 BOM output.

Merge objects are mutable. Fixtures and factories must return fresh data for every
test, and a test must not rely on state left behind by another test.

Prefer semantic assertions over large text snapshots. Exact string assertions are
appropriate only when formatting or encoding is itself part of the contract.

## Synthetic integration tests

The corpus under `tests/fixtures/micro_game/` is the complete hermetic integration
fixture. Keep it minimal and readable. Add only original synthetic data needed to
exercise a behavior; never copy proprietary Victoria 3 files into the repository.

The end-to-end suite must continue to verify that:

1. absorbed states disappear and the surviving state receives the expected map,
   building, population, ownership, state-history, and trade data;
2. missing hubs fall back correctly and map-object IDs are removed or retargeted;
3. localization inherits valid names and rejects placeholder names;
4. copy, aggregate-replacement, and aggregate-removal directories behave correctly;
5. standalone state references change while protected compound identifiers such as
   `STATE_BETA_ANJOU` remain intact;
6. required generated files use UTF-8 with BOM and representative outputs can be
   parsed again by `pyradox`;
7. two clean runs produce identical file lists and bytes;
8. rerunning into an existing output directory removes stale regular files;
9. the CLI can execute the same micro-game pipeline successfully.

Write all generated test output beneath pytest's `tmp_path`. Tests must not write to
the repository fixtures, a game installation, or a user's mod directory.

## Expected failures

Use `pytest.mark.xfail(strict=True, reason=...)` only for a confirmed production
defect with a minimal reproduction. The reason must identify the broken behavior.
Strict mode is required so that an unexpected pass forces removal or revision of the
xfail when the defect is fixed.

Do not use xfail for flaky setup, missing optional software, incomplete tests, or to
avoid fixing an incorrect assertion. Optional environmental tests should skip with a
clear reason instead.

## Installed-game smoke test

The live smoke test is optional and excluded from hosted CI. Run it against an
up-to-date local installation with:

```sh
VIC3_GAME_ROOT="/path/to/Victoria 3/game" uv run --locked pytest -m live --no-cov
```

The live test reads the game data and writes its plan, cache, and generated mod only
under `tmp_path`. It must never alter the installation. It demonstrates that the
current parser and pipeline can process that installed game version; it does not
launch Victoria 3 or prove that the generated mod is playable.

## Manual in-game validation

When release confidence requires playtesting, keep it separate from pytest results.
At minimum:

1. generate the mod from the intended merge plan and game version;
2. enable only the required mod set and start a new campaign in debug mode;
3. review `error.log` for parse, missing-reference, and localization errors;
4. inspect merged borders, ownership, buildings, population, hubs, names, and trade;
5. save, reload, and confirm that the merged states remain functional.

Record the date, game version, tested commit/build, merge plan, enabled mods, tested
scenario, pass/fail/partial result, relevant log findings, and whether save/reload was
tested. Without that record, report only the automated or live-smoke result—not an
in-game pass.

## CI policy

`.github/workflows/ci.yml` runs the non-live suite, Ruff lint and formatting checks,
the package build, and an import/CLI smoke check on pushes and pull requests. Pyright
runs with `continue-on-error` until its configuration and existing diagnostics are
addressed separately.

Do not lower the coverage threshold, remove assertions, broaden exclusions, or add
xfails merely to make CI pass. Any intentional testing-policy change must be explained
in the same review as the configuration change.
