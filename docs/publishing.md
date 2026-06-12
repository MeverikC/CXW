# Publishing CXW

This checklist prepares CXW for GitHub, TestPyPI, and PyPI distribution.

## Before Publishing

1. Choose and verify the package name.

   ```bash
   python -m pip index versions cxw
   ```

   The public package name is currently `cxwa` because `cxw` is unavailable on
   PyPI. Keep the CLI command as `cxw` under `[project.scripts]`.

2. Replace placeholder project URLs in `pyproject.toml`.

   ```toml
   [project.urls]
   Documentation = "https://github.com/<owner>/<repo>/tree/main/docs"
   Issues = "https://github.com/<owner>/<repo>/issues"
   Source = "https://github.com/<owner>/<repo>"
   ```

3. Decide the license and add a `LICENSE` file.

   Do not publish with an implied license. Add a license file, then add the
   matching license metadata/classifier to `pyproject.toml`.

4. Make sure runtime secrets and generated state are not tracked.

   ```bash
   git status --short
   git check-ignore -v .codex/cxw/main-1/auth.json
   git check-ignore -v demo/lottery/.codex/cxw/main-1/auth.json
   ```

5. Install development dependencies.

   ```bash
   python -m pip install -e ".[dev]"
   ```

6. Run tests.

   ```bash
   PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider
   ```

## Build Locally

Install the build frontend if needed:

```bash
python -m pip install -e ".[publish]"
```

Build source and wheel distributions:

```bash
python -m build
```

Check distribution metadata:

```bash
python -m twine check dist/*
```

Inspect the wheel contents:

```bash
python -m zipfile --list dist/*.whl
```

Confirm the prompt markdown files are included:

```bash
python -m zipfile --list dist/*.whl | grep 'cxw/prompts/.*\\.md'
```

## TestPyPI Dry Run

Create a TestPyPI API token, then upload:

```bash
python -m twine upload --repository testpypi dist/*
```

Install from TestPyPI in a clean environment:

```bash
python -m venv /tmp/cxw-testpypi
/tmp/cxw-testpypi/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  cxwa
/tmp/cxw-testpypi/bin/cxw --help
```

## PyPI Release

Create a PyPI API token and upload:

```bash
python -m twine upload dist/*
```

After upload:

```bash
python -m pip install --upgrade cxwa
cxw --help
```

## GitHub Release

Recommended release flow:

1. Update `pyproject.toml` version.
2. Update README and docs for changed behavior.
3. Run tests and build checks.
4. Commit the release.
5. Tag it.

   ```bash
   git tag v0.1.0
   git push origin main --tags
   ```

6. Create a GitHub release from the tag.

## GitHub Actions Secrets

For automated publishing, configure repository secrets:

```text
PYPI_API_TOKEN
TEST_PYPI_API_TOKEN
```

The included publish workflow is manual by default. Trigger it from GitHub
Actions only after the checklist above is complete.
