# AGENTS.md — Fluorescence MicroDrop plugin

Code style, import ordering, Traits typing, and the pub/sub conventions are
Microdrop's: read `AGENTS.md` and `docs/CLAUDE.md` in
https://github.com/Blue-Ocean-Technologies-Inc/Microdrop before writing code
here. This file covers what is specific to this plugin.

## Packages

- `fluorescence_controller` — backend: `PeripheralDeviceControllerBase` subclass,
  serial proxy, `on_<topic>_request` handlers, `consts.py` with the topics
  and `ACTOR_TOPIC_DICT`.
- `fluorescence_controls_ui` — dock pane, status-bar icon, `BaseMessageHandler`
  subclass with `_on_<topic>_triggered` handlers.
- `fluorescence_protocol_controls` — protocol-tree column(s).

UI and protocol-controls may import the backend's `consts` and data models;
they never import each other (enforced by `.importlinter`). From Microdrop
plugins only `consts` modules are imported.

## Environment and tests

This repo is not a pixi workspace. Clone it under
`pixi-microdrop/microdrop-py/` and use that workspace's `test` environment,
which has Microdrop's `src` on the path and no released copy of this plugin:

    pixi run --manifest-path ../pyproject.toml -e test python -m pytest -q

CI runs the pure-unit tests the same way on every PR (`unit-tests.yml`).

## Hooks and releases

`pixi run setup-hooks` (from `pixi-microdrop/microdrop-py`) installs the
pre-commit hooks: Conventional Commits, ruff, copyright header, import-section
headers, import-linter. Every push to `main` with a `feat`/`fix`/`refactor`/
`perf` commit publishes a new version to `prefix.dev/microdrop-plugins`;
other commit types do not release.
