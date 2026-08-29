# Authoring cases

The case directory is the engineer-owned source of simulation intent. Use the
generated reference to choose values; use the adapter status to decide whether
the current implementation can apply them.

## Find an entry

Browse the [dictionary reference](../reference/index.md), use site search, or
query the packaged catalog:

```bash
fluent-case reference show 'constant/physics.yaml#/solver/time'
fluent-case reference search 'pressure velocity coupling'
fluent-case reference list --document boundary-conditions --status planned
```

Canonical IDs are a dictionary path followed by an RFC 6901-style JSON pointer.
`*` means one list item or mapping key; it is documentation notation, not an
authored literal key.

## Read the three option layers

For every entry, distinguish:

1. **Static schema choices** — values accepted by the case loader. These are the
   safe values to author and version in Git.
2. **Runtime Fluent choices** — active objects, allowed values, and limits in one
   Fluent version and case state. They may narrow or extend what a generic
   authoring model can express.
3. **Adapter support** — the subset this repository can execute. `planned` means
   validation works but real apply must stop rather than guess.

For example, the schema accepts:

```yaml
solver:
  time: transient
```

The entry reports the official PyFluent path
`setup.general.solver.time`, but currently marks the adapter mapping `planned`.
That is useful, honest documentation: the intended coupling is visible without
pretending it has been implemented.

## Conditional fields

Discriminated objects expose only the fields belonging to their selected
variant. A reference entry lists `available_in` and `required_in` contexts. For
example, `/turbulence/near_wall` is meaningful for `type=k_epsilon`, not for
`type=laminar`.

Runtime activation is a separate issue. A YAML field can be structurally valid
yet inactive in Fluent until an upstream model or mesh state exists. Follow the
entry's activation/order note and the stage DAG.

## Quantities and units

Quantities use an explicit value and unit:

```yaml
operating_pressure:
  value: 101325
  unit: Pa
```

The entry shows curated allowed units where the schema has a semantic unit
validator. PyFluent may report a display unit; adapters must convert or pass an
explicit unit-bearing value rather than relying on an engineer's GUI defaults.

## Version and provenance

- Treat the target Fluent release in the catalog as part of a mapping's evidence.
- Lock mesh, case/data, chemistry, profile, and table inputs by SHA-256.
- Keep machine-local paths out of reusable YAML.
- Use an audited TUI escape only when a settings API gap, exact version, command,
  reason, and observable postcondition are recorded.
- Do not infer scientific success from orchestration completion. Objectives and
  case-local judgments remain engineer-defined and may evolve during investigation.

## Validate before Fluent

```bash
fluent-case validate case --platform scnet-cpu-small
fluent-case plan case --platform scnet-cpu-small
fluent-case apply case --platform scnet-cpu-small --adapter recording
```

The recording adapter exercises orchestration without claiming that solver
settings or physical results were verified.
