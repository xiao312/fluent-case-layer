# Contributing

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
python -m fluent_case_layer.reference check --root .
mkdocs build --strict
```

Install the optional `fluent` extra only in an environment intended to launch
or connect to Fluent. Schema validation, planning, fake execution, and most
tests must not need a license.

## Change discipline

- Add or update a test for every schema or stage-contract change.
- Preserve backward compatibility or include a schema migration note.
- Do not commit proprietary meshes, Fluent case/data files, chemistry tables,
  credentials, raw Slurm logs, or machine-local paths.
- Example cases must state asset, execution, numerical, and scientific status
  separately.
- TUI support requires a documented settings-API gap and an observable
  postcondition.
- Update `src/fluent_case_layer/reference/couplings.yaml` when a schema field's
  Fluent concept, PyFluent path, runtime option source, or adapter support changes.
- Never edit generated reference Markdown or `catalog.json` directly. Run
  `python -m fluent_case_layer.reference build --root .`, then commit all outputs.
- Mark a mapping `implemented` only with a version-qualified transform and an
  adapter test that checks an observable postcondition.

## Pull requests

Describe the authored intent affected, compiled-plan changes, validation run,
and any solver/version assumptions. Attach only curated evidence; reference
large artifacts by immutable digest.
