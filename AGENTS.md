# AGENTS.md

## Project overview

Victoria 3 state merging tool. Reads a merge plan JSON and game data files, outputs a complete mod directory.

## Commands

- **Install (dev):** `uv sync`
- **Run CLI:** `uv run state-merger-cli <merge_file> <game_root> <mod_dir>`
- **Run GUI:** `uv run state-merger` (tkinter GUI)
- **Run tests:** `uv run pytest`
- **Build wheel/sdist:** `uv build`
- **Build Windows EXE:** `uv run pyinstaller -F -n state-merger -p "src" -w -i "docs/images/states.dds" -y --clean src/vic3_state_merger/gui.py`

## Architecture

- **Package:** `src/vic3_state_merger/` — installed as `vic3_state_merger`
- **Entry points:** `cli.py` (CLI), `gui.py` (tkinter GUI), `__main__.py` delegates to CLI
- **Core:** `state_merger.py` — `StateMerger` class orchestrates all merging
- **Data modules:** `states.py`, `buildings.py`, `pops.py`, `trade.py`, `state_regions.py`, `map_object_data.py` — each parses a game data category and implements merge logic
- **Bundled assets:** `assets/` — static game data overrides shipped as Python string constants (state traits, USA flag definitions, USA state counter)
- **Tests:** `tests/` — currently only `__init__.py`; pytest configured with `--cov=src`

## Key conventions

- Uses `pyradox` (pyradox-txt-parser) for Paradox `.txt` file parsing; `pyyaml` for localization YML
- Versioning via `setuptools_scm` from git tags (`vX.Y.Z`); `SETUPTOOLS_SCM_PRETEND_VERSION` used in CI when not on a tag
- All output files written with UTF-8 BOM (`utf-8-sig`)
- `merge_states.json` at repo root is the default vanilla state list (no merges); values are empty arrays
- Release workflow (`.github/workflows/release.yml`) builds EXE + wheel on tag push or manual dispatch

## Gotchas

- The `parse_merge` helper merges all `.txt` files in a directory into a single `pyradox.Tree`; `merge_levels` parameter differs per data type (1 for map_data, 2 for others)
- Keyword replacement in misc data files uses word-boundary regex — state IDs are matched as whole tokens even inside compound identifiers
- Localization YML files have Vic3-specific numbered keys (`:0 "text"`) that must be cleaned via `clean_v3_yml_numbered_keys` before `yaml.safe_load`
