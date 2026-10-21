# Contributing

Thanks for looking. The most useful contribution is a **clip that was judged wrongly** — a false
positive (a good take failed) or a false negative (a bad take passed).

## Before you open a PR

1. Open an issue first for anything larger than a typo.
2. Run `pip install -e ".[dev]" && pytest -q && takecheck selftest`.
3. Add a test for the behaviour you changed. New checks need a synthetic fixture built with `ffmpeg`
   (see `src/takecheck/selftest.py`) so that no user footage is needed.

## Scope

`takecheck` judges **technical usability**, not taste. Checks must be deterministic arithmetic on
extracted frames or on ffprobe metadata. A check that needs a model belongs behind the optional
`vlm` judge, never in the default path.

## Style

- Python 3.10+, `ruff check` must pass.
- No new runtime dependency unless it is small, pure and unavoidable — the tool must stay installable
  in an environment where PyTorch is not welcome.

## Commit messages

Short imperative subject, then *why* in the body when the change is not obvious.
