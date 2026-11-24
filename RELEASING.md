# Releasing ReSrijan

Releases go to PyPI automatically when a GitHub release is published (`.github/workflows/release.yml`, PyPI trusted publishing: no token in the repository).

## One-time setup

1. **PyPI publisher.** Sign in at <https://pypi.org> (enable two-factor authentication), then *Account → Publishing → Add a new pending publisher*:
   * PyPI project name: `resrijan`
   * Owner: `rbiswasgroup`, repository: `resrijan`
   * Workflow: `release.yml`, environment: `pypi`
2. **GitHub environment.** In the repository: *Settings → Environments → New environment* named `pypi`. Optionally add yourself as a required reviewer, so each upload waits for one click.
3. **Repository page.** *Settings → General → Social preview*: upload `docs/images/resrijan-social-preview.png`. In the *About* box (gear icon) set the description, the website (`https://pypi.org/project/resrijan/`) and topics (`plot-digitizer`, `scientific-figures`, `data-extraction`, `matplotlib`, `ocr`, `chemistry`).

## Each release

1. Make sure CI is green on `main` (tests on Python 3.10, 3.12 and 3.13, every example, and the ground-truth validation).
2. Set the version in `pyproject.toml`, `resrijan/__init__.py` and `CITATION.cff` (`version`, `date-released`), and add a section to `CHANGELOG.md`.
3. Check the package locally:

   ```bash
   pip install build twine
   python -m build
   twine check dist/*
   ```

4. Commit, then on GitHub *Releases → Draft a new release*: tag `vX.Y.Z` (it must match the version in `pyproject.toml`), title `ReSrijan X.Y.Z`, paste the CHANGELOG section, attach nothing, and *Publish*. The `Release` workflow builds the sdist and wheel, checks them, and uploads them to PyPI.
5. Check the result: `pip install --upgrade resrijan` in a fresh virtual environment, then `resrijan --version`.

## Optional

* **Zenodo DOI.** Sign in to <https://zenodo.org> with GitHub, enable the `resrijan` repository under *GitHub*, then publish the release: Zenodo archives it and mints a DOI. Add the DOI badge to `README.md` and the `doi:` field to `CITATION.cff`.
* **Test run.** To try the upload first, add a pending publisher on <https://test.pypi.org> the same way and temporarily set `repository-url: https://test.pypi.org/legacy/` on the publish step.
