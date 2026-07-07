# fluorescence-microdrop-plugin

MicroDrop fluorescence peripheral plugin: serial board driver
(`fluorescence_controller`, backend) and status/controls dock pane
(`fluorescence_controls_ui`, frontend), mirroring the heater/magnet plugin
layout. Runtime-toggleable via Tools > Peripherals (groups declared in
`microdrop_plugin.toml`).

One-time setup per clone:

    pre-commit install --hook-type commit-msg --hook-type pre-commit

Releases are commitizen-driven from conventional commits; pushes to `main`
with release-worthy commits publish the conda package to
prefix.dev/microdrop-plugins (see `.github/workflows/publish.yml`).
