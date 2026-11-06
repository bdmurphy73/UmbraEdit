# UmbraEdit — Project Scan & Structure

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
Documentation for the UmbraEdit project (renamed from novelWriter).

This document is a structural scan of the **UmbraEdit** codebase. It is intended for developers who want to modify or extend the project.

> UmbraEdit was created by cloning **novelWriter** (vkbo/saga-soft) into this folder and renaming the project to `UmbraEdit`. The full upstream git history is preserved (see §6).

---

## 1. Overview

| Property | Value |
|---|---|
| **Project name** | UmbraEdit |
| **Origin** | Renamed/rebased from [novelWriter](https://github.com/vkbo/novelWriter) (vkbo / saga-soft) |
| **Inherited version** | 26.3b1 (novelWriter v26 series; see `umbraedit/__init__.py`) |
| **Base version** | Based on novelWrite 2026.02 by Veronica Berglyd Olsen (novelWriter.io), GPL v3.0 |
| **Language** | Python 3.11+ |
| **UI framework** | Qt6 via PyQt6 |
| **Platforms** | Linux, Windows, macOS |
| **Storage model** | Plain-text project files (one document per scene + a project XML), well suited to Git and file-sync tools |
| **Formatting** | Minimal Markdown-like syntax plus a metadata syntax for comments, synopsis, and cross-references |
| **License** | `GPL-3.0-or-later AND Apache-2.0 AND ISC AND MIT` (see `pyproject.toml`, `LICENSE.md`) |
| **Entry point** | `UmbraEdit.py` → `umbraedit:main()` |

**Core idea:** a novel is built from many small plain-text documents organised in a binder/tree, with a composing editor and a compile/export step (DOCX, EPUB, HTML, ODT, Markdown, raw text, QDoc).

---

## 2. Repository layout (top level)

```
UmbraEdit/                          <- this folder (was novelWriter2)
├── UmbraEdit.py                    <- application start script (imports umbraedit, calls main)
├── pyproject.toml                  <- project metadata, dependencies, ruff/pytest config
├── uv.lock                         <- dependency lockfile (regenerate if deps change)
├── run_tests.py                    <- pytest runner wrapper
├── pkgutils.py                     <- packaging / i18n utility script
├── README.md                       <- user-facing project page (mechanically renamed to UmbraEdit)
├── LICENSE.md
├── CHANGELOG.md                    <- historical novelWriter changelog (retains original attribution)
├── CONTRIBUTING.md
├── CREDITS.md
├── AI_POLICY.md
├── .gitignore
├── .env.example
├── docs/                           <- Sphinx documentation source
├── i18n/                           <- Qt translation sources (ue_XX.ts) — compiled .qm are gitignored
├── sample/                         <- sample novel project (.nwx + content)
├── setup/                          <- packaging: deb, windows, flatpak, macOS, appimage, icons
├── tests/                          <- pytest suite (core, editor, gui, manuscript, models, story, text, tools, …)
├── umbraedit/                      <- main Python package (was novelwriter/)
└── utils/                          <- build scripts (appimage, debian, flatpak, pypi, windows, assets, docs)
```

**Note:** `AGENTS.md` is gitignored by this project (`.gitignore` line 68). This scan lives in `UMBRAEDIT.md` instead.

---

## 3. Package layout — `umbraedit/`

| Module / package | Responsibility |
|---|---|
| `__init__.py` | Application bootstrap, `__version__`, `main()` entry |
| `config.py` | Runtime configuration, paths, locale/i18n loading (`_ueLangPath`) |
| `constants.py` | Application-wide constants |
| `shared.py` | Shared data / singleton state |
| `enum.py`, `types.py`, `error.py` | Enums, shared types, error handling |
| `splash.py` | Splash screen |
| `guimain.py` | Main window / GUI assembly |
| `core/` | Project model: project, projectdata, projectxml, tree, item, document, storage, sessions, index, indexdata, projectsearch, spellcheck, status, options, coretools |
| `editor/` | The composing editor: editor, editordocument, highlighter, history, hovercard, header/footer, toolbars, viewer, search, completion, vim mode |
| `gui/` | Widgets/views: main menu, novel tree, project tree, sidebar, status bar, item details, search, theme |
| `manuscript/` | Compile/export: manuscript build, document build, settings |
| `models/` | Qt item models: item, novel, outline, search |
| `story/` | Outline/story view, story settings |
| `text/` | Text processing: counting, patterns, formats, autoreplace |
| `tools/` | Dictionaries, lorem ipsum, welcome, writing stats |
| `formats/` | Import/export filters: to/from DOCX, EPUB, HTML, ODT, Markdown, QDoc, raw text, TOML, QDoc |
| `dialogs/` | Preferences, project settings, about, split/merge, labels, links, quotes, word list |
| `extensions/` | Custom widgets: tab widget, switch, progress bars, event filters, etc. |
| `assets/` | Icons, images, themes (`.toml`), i18n project JSON, manual, credits |

---

## 4. How to build and run

### Requirements
- Python ≥ 3.11 (system Python 3.9.6 is **too old** — `match`/`case` syntax requires 3.10+)
- `pyqt6>=6.4`, `pyenchant>=3.3.0`
- macOS only: `pyobjc-framework-Cocoa`

### Run the application
```bash
cd /Volumes/1TB_APL_Storage/UmbraEdit
python3 UmbraEdit.py
# or, with the package on PYTHONPATH:
python3 -c "import umbraedit; umbraedit.main()"
```

### Syntax check (Python 3.11+)
```bash
/Volumes/Dock/worstauthor/.local/bin/python3.11 -m py_compile umbraedit/*.py umbraedit/**/*.py
```

### Tests
```bash
python3 run_tests.py                 # full pytest suite
python3 run_tests.py -m core         # run a test marker group
```
Test configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`, testpaths=`tests`).

### Linting
The project uses **ruff** (see `[tool.ruff]` in `pyproject.toml`) and **pyright**.

### Packaging
See `setup/` and `utils/`:
- `utils/build_debian.py`, `build_windows.py`, `build_flatpak.py`, `build_appimage.py`, `build_pypi.py`
- `setup/windows/`, `setup/macos/`, `setup/debian/`, `setup/flatpak/`

---

## 5. i18n (translations)

- Translation sources: `i18n/ue_XX.ts` (renamed from `nw_XX.ts`)
- Compiled `.qm` files are **gitignored** (`i18n/*.qm`, `/umbraedit/assets/i18n/*.qm`) and generated at build time
- `umbraedit/config.py` loads `ue_<locale>.qm` from `_ueLangPath` (`umbraedit/assets/i18n`)
- Add a new language: create `i18n/ue_XX.ts` and regenerate the `.qm` with Qt Linguist / `lrelease`

---

## 6. Git system & Gitea publishing

### Current remote state
```
upstream   https://github.com/vkbo/novelWriter.git   (original novelWriter, preserved as reference)
```
There is **no `origin`** yet.

### What was done in this session
1. Cloned `https://github.com/vkbo/novelWriter.git` into this folder (`novelWriter2`).
2. Renamed the project `novelWriter` → `UmbraEdit` (package `novelwriter` → `umbraedit`, entry `novelWriter.py` → `UmbraEdit.py`, i18n `nw_*.ts` → `ue_*.ts`, packaging files, all imports/docs/tests/workflows).
3. Committed the rename:
   - `70d74e675 chore: rename project from novelWriter to UmbraEdit` (474 files, all renames detected by git)
4. Archived the previous UmbraEdit (Rust/Tauri, pre-implementation spec project) preserving its git history:
   - `/Volumes/1TB_APL_Storage/Archive/UmbraEdit_archived_20261105/`
5. Working tree is clean; branch is `main`.

### To publish as UmbraEdit on your Gitea server
A Gitea credential is **not** configured in this environment, and the Gitea server URL is not known yet, so `origin` was intentionally left unset. When ready:

```bash
# 1. Create the "UmbraEdit" repository on your Gitea server first
# 2. Add it as origin
git remote add origin <GITEA_URL>/UmbraEdit.git

# 3. Push
git push -u origin main

# 4. (Optional) keep pulling upstream novelWriter improvements
git fetch upstream
git merge upstream/main   # or cherry-pick as desired
```

### Project URLs to update
`README.md` and `pyproject.toml` currently carry mechanically-renamed GitHub URLs
(`https://github.com/saga-soft/UmbraEdit`, etc.). Before publishing, replace these
with your Gitee instance URLs, e.g.:
- Repository → `https://<gitea>/<owner>/UmbraEdit`
- Issues → `https://<gitea>/<owner>/UmbraEdit/issues`
- Homepage / Documentation → your UmbraEdit docs site

---

## 7. Extension guidance (adding features)

The codebase is organised by concern, which makes it straightforward to extend:

| To add… | Touch… |
|---|---|
| New editor feature / syntax highlighting | `umbraedit/editor/` (editor, highlighter, history) |
| New project-tree / binder operation | `umbraedit/core/` (tree, project, projectdata, projectxml) |
| New import/export format | `umbraedit/formats/` (add a `toXxx` / `fromXxx` module) |
| New settings / preferences UI | `umbraedit/dialogs/preferences.py`, `umbraedit/config.py` |
| New view / dock panel | `umbraedit/gui/`, `umbraedit/guimain.py` |
| New data model / Qt model | `umbraedit/models/`, `umbraedit/core/item.py` |
| New compile/export target | `umbraedit/manuscript/` + a format module |
| New theme | `umbraedit/assets/themes/*.toml` |
| New translation | `i18n/ue_XX.ts` (§5) |

### Recommended workflow for new features
1. Create a feature branch off `main`: `git checkout -b feature/<name>`
2. Implement + add tests under `tests/` mirroring the source layout
3. Run `python3 run_tests.py` and `ruff` lint
4. Commit on the feature branch, then merge to `main`
5. Never let a week of work sit uncommitted (per project convention)

---

## 8. Files intentionally left as-is

| File | Reason |
|---|---|
| `uv.lock` | Dependency lockfile; still references `novelwriter` — regenerate (`uv lock`) if dependencies change |
| `setup/windows/novelWriter.exe` | Binary executable |
| `umbraedit/assets/images/welcome.webp` | Binary image (may still render "novelWriter" text) |
| `CHANGELOG.md`, `CREDITS.md` | Historical records retaining original novelWriter attribution |

---

*Generated as part of the UmbraEdit project setup. Scan date: 2026-11-05.*
