# Documentation system

The documentation is one product with two readers: an engineer navigating a
searchable manual, and an agent asking deterministic questions of a JSON
catalog. Both views are built from the same sources.

```text
Pydantic models ──> JSON Schema ───────────────┐
                                               ├─> generated Markdown reference
reviewed couplings.yaml ───────────────────────┤
                                               └─> catalog.json ─> CLI / agents
live Fluent metadata snapshots ────────────────────────────────> case-state overlay
```

## Why this shape

The design combines useful patterns from four official documentation systems:

- OpenFOAM gives an individual boundary-condition page its properties, formula,
  usage dictionary, and implementation source. Its common-combination pages also
  make boundary coupling and stability advice explicit. See the official
  [boundary-condition overview](https://doc.openfoam.com/2606/tools/processing/boundary-conditions/),
  [`fixedValue` reference](https://doc.openfoam.com/2606/tools/processing/boundary-conditions/rtm/derived/general/fixedValue/),
  and [common combinations](https://doc.openfoam.com/2606/tools/processing/boundary-conditions/common-combinations/).
- Cantera's official [YAML input reference](https://www.cantera.org/stable/yaml/index.html)
  treats each field as an API: type, accepted forms, required/optional behavior,
  defaults, and examples are documented together.
- PyFluent's official [solver settings guide](https://fluent.docs.pyansys.com/version/dev/user_guide/solver_settings/solver_settings_contents.html)
  exposes a hierarchical settings tree and runtime metadata such as active state,
  read-only state, defaults, allowed values, minimum, and maximum. Those values can
  change after loading a mesh or enabling a model, so they cannot all be frozen in
  our YAML schema.
- MkDocs provides explicit navigation, built-in search, and a
  [strict build mode](https://www.mkdocs.org/user-guide/configuration/) suitable
  for CI drift and link checks.

OpenFOAM is documentation inspiration only. This project supports Fluent and
PyFluent; it does not expose an OpenFOAM adapter or compatibility contract.

## Sources of truth

### 1. Pydantic schema: authored syntax

Files under `src/fluent_case_layer/schema/` own:

- key names and nesting;
- scalar and container types;
- required versus optional fields;
- static defaults, enums, literals, bounds, and patterns;
- discriminated variants and cross-document validation.

The generator walks the validation JSON Schema and assigns each key a canonical
ID such as `constant/physics.yaml#/solver/time`. List items and mapping keys use
`*`, for example `system/control.yaml#/stages/*/iterations`.

### 2. Coupling registry: reviewed semantics

`src/fluent_case_layer/reference/couplings.yaml` owns information that JSON
Schema cannot know:

- the corresponding Fluent concept or panel;
- activation and ordering dependencies;
- the PyFluent interface, path or command, and operation;
- whether options are static or must be discovered at runtime;
- path confidence and Fluent-version qualification;
- current adapter status and option-specific support;
- a link to the implementation boundary and a precise gap note.

The registry supports document defaults, path patterns, and exact entry
overrides. Exact keys and patterns are validated during generation. An unknown
key or unmatched pattern fails the build.

### 3. Runtime snapshot: state-specific facts

A live Fluent settings tree may report a different active object set or allowed
values after a model transition. Such observations belong in a versioned runtime
snapshot tied to Fluent version and case state; they never silently rewrite the
authored schema or coupling registry. See [runtime discovery](runtime-discovery.md).

## Support states

| Status | Meaning |
| --- | --- |
| `implemented` | The documented case field compiles to a supported adapter operation under the stated conditions. |
| `partial` | Only named options or prerequisites are implemented; inspect `option_support` and the note. |
| `planned` | The case field validates, but the adapter deliberately fails closed without a mapping. |
| `declaration_only` | The compiler/evidence system consumes it; it is not a Fluent setting. |
| `not_applicable` | Metadata with no Fluent/PyFluent setting counterpart. |

This vocabulary prevents three common category errors: Fluent supporting a
feature does not mean PyFluent exposes the same stable path; PyFluent exposing a
path does not mean this adapter maps it; a successful solver command does not
make a numerical or scientific judgment.

## Generated products

`python -m fluent_case_layer.reference build --root .` creates:

- one Markdown page for each split dictionary;
- an entry index and implementation coverage matrix;
- copies of every JSON Schema for the documentation site;
- `docs/reference/catalog.json` for web clients;
- the packaged `fluent_case_layer/reference/catalog.json` used by the CLI.

Never hand-edit a file carrying the generated marker. Edit the schema or
coupling registry and rebuild it.

## Change workflow

1. Change the Pydantic model when authored syntax changes.
2. Add or update coupling metadata for new semantics.
3. Add adapter behavior and observable tests before marking a path implemented.
4. Run the generator.
5. Run `python -m fluent_case_layer.reference check --root .`.
6. Run `mkdocs build --strict`, Ruff, and Pytest.

CI repeats the drift check and strict site build on all supported Python versions.
