# Agent guide

Use the reference catalog as the authoritative discovery interface before
editing a case or proposing a PyFluent mutation. Do not infer a mapping from a
similar field name.

## Query contract

The packaged `catalog.json` is deterministic and has these top-level keys:

| Key | Purpose |
| --- | --- |
| `catalog_version` | Machine contract version. |
| `target` | Fluent/PyFluent release and qualification policy. |
| `policy` | Meanings of option layers, statuses, and confidence. |
| `generated_from` | SHA-256 digests of schema and coupling sources. |
| `documents` | Dictionary inventory and human reference pages. |
| `coverage` | Counts by document and implementation status. |
| `entries` | Complete ordered entry records. |

Each entry contains its canonical `id`, document, pointer, description, schema
facts, Fluent/PyFluent coupling, support boundary, and human-page anchor.

Use the CLI for stable JSON output:

```bash
fluent-case reference show 'system/control.yaml#/stages/*/iterations'
fluent-case reference search 'hybrid initialization' --limit 5
fluent-case reference list --status implemented
```

Python callers can use:

```python
from fluent_case_layer.reference import find_entries, get_entry, load_catalog

entry = get_entry("constant/physics.yaml#/solver/time")
planned = find_entries(document="physics", status="planned")
catalog = load_catalog()
```

## Decision procedure

Before authoring or changing one field:

1. Resolve the exact canonical entry ID.
2. Check `schema.choices`, `schema.constraints`, `schema.available_in`, and any
   curated `allowed_units`.
3. Check the Fluent activation/order note.
4. Check `coupling.pyfluent.option_source`. If it includes runtime metadata,
   do not invent state-dependent values.
5. Check `coupling.adapter.status`.
6. For `partial`, select only an option explicitly marked implemented.
7. For `planned`, preserve the intent but do not claim real apply support. Add a
   reviewed mapping or an audited case-specific explicit operation.
8. Record the exact overlay, rationale, observed state, and evidence in an attempt.

## Status behavior

- `implemented`: execution is allowed only under the documented conditions.
- `partial`: inspect `option_support` and notes; absence means stop and inspect code.
- `planned`: validation and planning are allowed; automatic PyFluent mutation is not.
- `declaration_only`: use it in compiler/evidence reasoning, never as a solver path.
- `not_applicable`: do not search Fluent for a counterpart.

Path confidence is independent. `official` means the official PyFluent docs show
the path; it does not mean our adapter implements it. `candidate` means the path
must be checked against the target Fluent version. `dynamic` means named objects
or active fields must be resolved from the live session.

## Human escalation

Interrupt an engineer when a choice changes physical interpretation, geometry or
mesh intent, boundary meaning, chemistry reduction, experimental alignment, or
resource commitment. The catalog explains mechanics; it does not replace current
engineering judgment or create a universal acceptance contract.

## Updating the reference

An agent adding a mapping must update `couplings.yaml`, add adapter tests with an
observable postcondition, regenerate outputs, and pass the drift/strict-doc checks.
Never patch generated Markdown or `catalog.json` directly.
