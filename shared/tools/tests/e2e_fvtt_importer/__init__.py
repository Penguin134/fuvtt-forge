"""Opaque-box 4-tier E2E test infrastructure for `mods/fvtt-world-importer/`."""

from __future__ import annotations

DEFAULT_OPTIONS: dict[str, object] = {
    "proxy": "",
    "import_scenes": True,
    "import_characters": True,
    "import_monsters": True,
    "include_hidden": True,
    "skip_missing_assets": True,
}
