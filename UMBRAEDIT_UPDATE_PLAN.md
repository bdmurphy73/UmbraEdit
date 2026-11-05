# UmbraEdit — Toolchain & Dependency Update Plan

Copyright (C) 2026 B.D. Murphy.
Plan for upgrading UmbraEdit (Python/PyQt6) toolchain and dependencies.

**Goal:** Bring UmbraEdit (Python/PyQt6) up to the latest stable versions of its tools and dependencies, starting from the current baseline.

**Baseline (as of 2026-11-05):**
- System Python: 3.9.6 (`/usr/bin/python3`) — **below** the project's `requires-python >=3.11`
- Available runtimes: Python 3.11.15, 3.12.13 (via `uv` in `~/.local/bin`)
- `uv`: 0.11.7 (2026-04-15) — outdated
- PyQt6: not yet installed in the 3.11 environment
- `pyproject.toml` deps: `pyqt6>=6.4`, `pyenchant>=3.3.0`, `pyobjc-framework-Cocoa` (darwin)
- Lockfile: `uv.lock` (references `novelwriter` package name — will need regen)

---

## 1. Target Versions

| Tool | Current | Target | Source |
|---|---|---|---|
| Python runtime | 3.9.6 (system) | 3.12.x (latest 3.12) or 3.13.x | `uv` / python.org |
| PyQt6 | not installed | latest 6.x | PyPI |
| pyenchant | >=3.3.0 | latest 3.x | PyPI |
| pyobjc-framework-Cocoa | pinned by pyproject | latest (macOS only) | PyPI |
| uv | 0.11.7 | latest | github.com/astral-sh/uv |
| ruff | (in `uv.lock`) | latest | PyPI |
| pyright | (in `uv.lock`) | latest | npm/PyPI |
| pytest | (in `uv.lock`) | latest 8.x | PyPI |
| pytest-qt | (in `uv.lock`) | latest | PyPI |
| coverage | (in `uv.lock`) | latest | PyPI |
| Sphinx + theme | (in `uv.lock`) | latest | PyPI |
| setuptools | 82.0.1 | latest | PyPI |
| pip | 26.0.1 | latest | ensure via `uv` |

> Prefer Python **3.12** as the primary target (mature, PyQt6 wheels widely available). Keep **3.11** as a secondary CI matrix entry since `requires-python` is `>=3.11`.

---

## 2. Phased Execution

### Phase 0 — Preparation & Safety
1. Ensure working tree is clean and all changes committed on `main` (already done).
2. Tag the current state as a rollback point:
   ```bash
   git tag umbraedit/pre-toolchain-update
   git push origin umbraedit/pre-toolchain-update
   ```
3. Record current working commands (`python3 UmbraEdit.py`, test runner) so you can compare before/after.
4. Back up `uv.lock` and `pyproject.toml`.

### Phase 1 — Upgrade `uv` and Python runtimes
1. Upgrade `uv` itself:
   ```bash
   uv self upgrade
   # or: curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Install the target Python(s) via `uv` (so they are isolated and reproducible):
   ```bash
   uv python install 3.12
   uv python install 3.11   # keep for CI matrix
   uv python list
   uv python pin 3.12        # sets default for this project (writes .python-version)
   ```
3. Verify:
   ```bash
   uv run python --version   # should report 3.12.x
   ```

### Phase 2 — Upgrade core runtime dependencies
Create a fresh virtual environment with the target Python and install the project's runtime deps at their latest compatible versions:

```bash
cd /Volumes/1TB_APL_Storage/novelWriter2
uv venv --python 3.12
uv pip install "pyqt6>=6.4" "pyenchant>=3.3.0"
# macOS only:
uv pip install "pyobjc-framework-Cocoa"
```

Then:
1. Run the app to confirm it starts:
   ```bash
   uv run python UmbraEdit.py
   # or, after venv activation:
   python UmbraEdit.py
   ```
2. If `pyqt6` wheels fail on the target Python, fall back to 3.11 or file an issue.

### Phase 3 — Upgrade build / lint / test tooling
Update the dependency groups in `pyproject.toml` (`build`, `docs`, `test`, `lint`) to latest, then sync:

```toml
[dependency-groups]
dev = [
    { include-group = "build" },
    { include-group = "docs" },
    { include-group = "test" },
    { include-group = "lint" },
]
build = ["pyyaml", "tzdata; sys_platform == 'win32'"]
docs = [
    "docutils>=0.17.1",
    "pygments>=2.7",
    "sphinx-book-theme",
    "sphinx-copybutton",
    "sphinx-design",
    "sphinx-favicon",
    "sphinx-intl",
    "sphinx>=5.0",
]
test = [
    "coverage>=7.16.0",
    "pytest-qt",
    "pytest-timeout",
    "pytest>=6.0.0",
    "tzdata; sys_platform == 'win32'",
]
lint = ["pyright", "ruff"]
```

Suggested edits:
- Bump `pytest>=6.0.0` → `pytest>=8.0` (check PyPI for latest 8.x)
- Bump `coverage>=7.16.0` → latest
- Bump `sphinx>=5.0` → latest 7.x/8.x
- Keep `ruff` and `pyright` unpinned or with generous lower bounds so `uv lock` resolves latest

Then sync:
```bash
uv lock --upgrade       # resolve all groups to latest
uv sync --all-groups    # create .venv with everything
```

### Phase 4 — Regenerate `uv.lock`
`uv.lock` currently references the old `novelwriter` package name and is stale.
```bash
uv lock --upgrade
git diff uv.lock   # review before committing
```
Commit the regenerated lockfile with the toolchain update.

### Phase 5 — Update `requires-python` and classifiers (optional)
If you want to drop 3.11 and standardize on 3.12+:
```toml
requires-python = ">=3.12"
```
And update classifiers accordingly. Otherwise keep `>=3.11` and test both 3.11 and 3.12 in CI.

### Phase 6 — Update Gitea CI workflows
The `.github/workflows/*.yml` files reference Python setup steps. Update them to:
- Use `actions/setup-python` with `python-version: ["3.11", "3.12"]` (or your Gitea Actions equivalent)
- Install via `uv sync --all-groups` instead of `pip install -e .`
- Run `uv run ruff check`, `uv run pyright`, `uv run pytest`

If your Gitea instance uses Gitea Actions, mirror the same matrix. If not, update the workflows to call `uv` explicitly.

### Phase 7 — Packaging scripts review
The `utils/` build scripts (`build_appimage.py`, `build_debian.py`, `build_flatpak.py`, `build_pypi.py`, `build_windows.py`) and `setup/` packaging may pin Python/Qt versions. Check each for:
- Hardcoded `python3` → should target the new runtime
- `qt_version = "6.11"` in `[tool.novelwriter.build] flatpak` → verify against latest Qt6
- `pyqt6>=6.4` lower bound → keep or raise

### Phase 8 — Validation
1. **Syntax/compile:** `uv run python -m py_compile umbraedit/ tests/ utils/`
2. **Import smoke:** `uv run python -c "import umbraedit; umbraedit.main(['--help'])"`
3. **Lint:** `uv run ruff check .` and `uv run pyright`
4. **Tests:** `uv run pytest` (or `uv run python run_tests.py`)
5. **App launch:** `uv run python UmbraEdit.py` — confirm main window opens
6. **Export formats:** exercise DOCX/EPUB/HTML/ODT export paths if sample data exists

### Phase 9 — Commit & publish
```bash
git add -A
git commit -m "chore: upgrade toolchain to Python 3.12 and latest deps

- Upgrade uv and pin Python 3.12 via .python-version
- Refresh pyproject.toml dependency groups to latest compatible versions
- Regenerate uv.lock
- Update Gitea CI workflows for uv + Python 3.11/3.12 matrix
- Review packaging scripts for hardcoded python/qt versions"
git push origin main
```

---

## 3. Rollback Plan

If anything breaks after the update:

```bash
# Restore previous state
git checkout umbraedit/pre-toolchain-update .
# or reset hard to the tag
git reset --hard umbraedit/pre-toolchain-update
git push origin main --force   # only if already pushed and you need to undo
```

Also keep the old system Python 3.9.6 available (do not remove `/usr/bin/python3`), and keep the `upstream` remote pointing at the original novelWriter for reference.

---

## 4. Recommended Command Sequence (copy-paste ready)

```bash
cd /Volumes/1TB_APL_Storage/novelWriter2

# 0. Tag rollback point
git tag umbraedit/pre-toolchain-update
git push origin umbraedit/pre-toolchain-update

# 1. Upgrade uv and pin Python 3.12
uv self upgrade
uv python install 3.12
uv python pin 3.12
uv run python --version

# 2. Create venv and install runtime deps at latest
uv venv --python 3.12
uv pip install "pyqt6>=6.4" "pyenchant>=3.3.0"

# 3. Smoke-test the app
uv run python UmbraEdit.py

# 4. Sync dev toolchains (lint/test/docs)
uv sync --all-groups

# 5. Regenerate lockfile
uv lock --upgrade
git diff uv.lock | head -100

# 6. Validate
uv run python -m py_compile umbraedit/ tests/ utils/
uv run ruff check .
uv run pytest
```

---

## 5. Notes & Risks

- **PyQt6 on Python 3.13:** Wheels may lag; if 3.13 is required, verify PyQt6 availability first. 3.12 is the safer target.
- **`pyobjc-framework-Cocoa`:** macOS-only; only install/test on darwin.
- **`uv.lock` diff:** Expect a large diff since the lockfile is stale; review that no unexpected major-version jumps occur (especially PyQt6 6.x → 7.x, which would be breaking).
- **CI:** Gitea Actions runners must have `uv` installed, or the workflows must install it as a step.
- **Application still runs on Python 3.9.6?** No — `match`/`case` syntax requires 3.10+, and `requires-python` is `>=3.11`. The system 3.9.6 must not be used to run UmbraEdit.
