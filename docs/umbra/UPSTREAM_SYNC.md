# Upstream Sync

## Adding the Upstream Remote

```bash
git remote add upstream https://github.com/vkbo/novelWriter.git
git fetch upstream
```

## Fetching a Specific Tag

```bash
git fetch upstream --tags
git log upstream/main --oneline -5
```

## Merging Upstream

```bash
git merge upstream/main
```

Resolve conflicts. The most common conflict points are:

- `umbraedit/gui/theme.py` — brand icon references
- `umbraedit/__init__.py` — version and branding
- `setup/` — packaging file names
- `pyproject.toml` — project name and entry points

## Resolving Brand Conflicts

After merging, run the brand audit to verify no upstream graphics leaked in:

```bash
python3 utils/umbra_brand_audit.py
```

If any file hash matches an upstream brand graphic, regenerate it:

```bash
python3 utils/umbra_make_icons.py
```

## Running Checks After Merge

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run run_tests.py -orl
python3 utils/umbra_upstream_check.py
python3 utils/umbra_brand_audit.py
```

## Recording the New Base

After a successful merge, update `docs/umbra/BASE.md` with the new
upstream commit hash and regenerate the changed-files list.
