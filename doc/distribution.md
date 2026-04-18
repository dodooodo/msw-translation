# Distribution & Release

## Overview

The app ships as a self-contained binary — no Python installation required for end users.

| Platform | Format | Built with |
|----------|--------|-----------|
| macOS (Apple Silicon) | `MSW Translator.app` in `.zip` | PyInstaller + `swiftc` |
| Windows x64 | `MSW Translator.exe` in `.zip` | PyInstaller + `dotnet publish` |
| Linux x64 | folder in `.tar.gz` | PyInstaller + system Tesseract |

## Automated CI releases

Push a version tag to trigger a full matrix build:

```bash
git tag v1.2.3
git push origin v1.2.3
```

`.github/workflows/release.yml` runs three parallel jobs (one per platform),
each producing a zipped artifact. All three are uploaded to the same GitHub Release.

`.github/workflows/ci.yml` runs the test suite on every push and pull request
(all three platforms, no build step) so regressions are caught before tagging.

### What each CI job does

**macOS**
1. `uv sync` — installs Python deps
2. `pytest tests/ -v` — runs the full test suite (fails fast on any regression)
3. `swiftc translate_apple.swift -o translate_apple` — compiles Swift translation helper
4. `pyinstaller translator.spec` — builds `dist/MSW Translator.app` (onedir + BUNDLE)
5. Zips the `.app` and uploads to the Release

**Windows**
1. `uv sync` — installs Python deps (includes `winrt-*` packages)
2. `pytest tests/ -v` — runs the full test suite
3. `dotnet publish translate_windows.csproj -r win-x64` — compiles C# translation helper
4. `pyinstaller translator.spec` — builds `dist/MSW Translator.exe` (onefile)
5. Zips the `.exe` and uploads to the Release

**Linux**
1. `apt install tesseract-ocr tesseract-ocr-kor …` — installs OCR engine + language packs
2. `uv sync` — installs Python deps
3. `pytest tests/ -v` — runs the full test suite
4. `pyinstaller translator.spec` — builds `dist/MSW Translator/` folder (onefile)
5. Tarballs the folder and uploads to the Release

## Building locally (macOS)

```bash
# Compile Swift helper (only needed once, or after translate_apple.swift changes)
swiftc translate_apple.swift -o translate_apple

# Install PyInstaller
venv/bin/python -m ensurepip
venv/bin/python -m pip install pyinstaller

# Build
venv/bin/pyinstaller translator.spec
# → dist/MSW Translator.app

# Package
zip -r "MSW-Translator-vX.Y.Z-macos-arm64.zip" "dist/MSW Translator.app"
```

## PyInstaller spec (`translator.spec`)

Platform-conditional bundling:

- **macOS** — onedir mode + `BUNDLE`: `translate_apple` binary is included as data,
  resolved at runtime via `_bundle_dir()` → `sys._MEIPASS`.
  `LSUIElement = True` suppresses the Dock icon (overlay app).
- **Windows** — onefile mode: `translate_windows.exe` is included as data,
  resolved the same way.
- **Linux** — onefile mode: no extra binaries needed (Tesseract is a system package).

## `_bundle_dir()` — binary path resolution

```python
def _bundle_dir() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS   # PyInstaller bundle
    return os.path.dirname(os.path.abspath(__file__))  # dev run
```

All subprocess helpers (`translate_apple`, `translate_windows.exe`) are located
relative to `_bundle_dir()`, so the same path logic works in both `uv run` and
packaged contexts.

## Releasing a new version (step by step)

1. **Bump `APP_VERSION`** in `version.py`:
   ```python
   APP_VERSION = "0.2.0"
   ```
2. Update `CLAUDE.md` / `README.md` if anything significant changed.
3. Commit and push to `main`.
4. Tag and push:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
5. GitHub Actions builds all three platforms automatically.
   Monitor at `https://github.com/dodooodo/msw-translation/actions`.
6. Users with the app installed will see the amber update banner on their next launch
   (the update checker compares against the latest GitHub release tag).

## Updating the community glossary

The in-app update notification for glossaries is driven by the top-level `"version"`
integer in [`msw-glossary/index.json`](https://github.com/dodooodo/msw-glossary).

1. Add or edit glossary files in `msw-glossary/glossaries/`.
2. Update `"entry_count"` for any changed entries in `index.json`.
3. Increment `"version"`:
   ```json
   { "version": 2, "glossaries": [ … ] }
   ```
4. Commit and push to `msw-glossary/main`.

Users whose local `community_glossary_seen_version` is less than the new `version` will
see "✨ 社群詞彙表有更新" on their next launch. Clicking **[立即更新]** opens the
community browser and saves the new seen version after import.

## Auto-compile on first use

When running from source (`uv run main.py`), the platform helper binary is compiled
automatically on first use if missing:

- **Apple engine** — `_ensure_apple_binary()` calls `swiftc translate_apple.swift`
- **Windows engine** — `_ensure_windows_binary()` calls `dotnet publish translate_windows.csproj`

This means contributors don't need to pre-compile; the first run handles it.
