# Contributing to ReSrijan

Thank you for helping! The most valuable contributions are **figures that ReSrijan gets wrong**.

## Reporting a problem

Open an issue with the *Extraction problem* template and attach:

1. the figure file (or a crop of it), if you may share it;
2. the command you ran;
3. the `*_report.html` and `*_overlay.png` from the output folder;
4. what the correct values are, if you know them.

Please do not attach figures you are not allowed to share. A re-drawn figure with the same features is just as useful.

## Development setup

```bash
sudo apt install tesseract-ocr ghostscript librsvg2-bin fonts-liberation
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # fast unit + end-to-end tests
python validation/make_testset.py testset && python validation/run_validation.py testset results
```

Every change to the extractors should keep `validation/RESULTS.md` at least as good. Please include the before/after table in your pull request.

## Adding a figure type or a test case

* Extractors live in `resrijan/extract/`; the pipeline that chooses between them is `resrijan/pipeline.py`.
* Add a ground-truth case to `validation/make_testset.py` (draw from known data, save in several formats, write `truth/<name>.json`) and a scorer in `validation/run_validation.py`.
* Add an example and a tutorial page in `examples/` and `docs/tutorials/`, then run `python tools/build_examples.py`.

## Adding a journal template

Templates are YAML files in `resrijan/templates/`. Please cite the publisher's author guidelines (URL and date) in a comment at the top of the file.

## Style

Python ≥ 3.10, readable names, docstrings on public functions, no new heavy dependencies without discussion. `ruff check .` should be clean.
