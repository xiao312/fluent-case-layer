# Repository working agreement

## Product intent

Build a solver-aware configuration compiler and state reconciler for Fluent,
not a collection of opaque automation scripts. User-authored case files must
remain readable, typed, versionable, and independent of machine-local paths.
This product is Fluent/PyFluent-only; OpenFOAM is a historical inspiration,
not an adapter or compatibility target. The primary users are the internal CFD
simulation team.

## Engineering rules

- Prefer PyFluent settings API operations; explicit TUI escapes must record a
  reason, Fluent-version constraint, exact command, and expected postcondition.
- Separate desired case intent, compiled plan, observed Fluent state, and run
  evidence.
- Treat stages as a dependency graph with typed inputs, outputs, preconditions,
  postconditions, retries, optional case-local judgments, and checkpoint
  evidence.
- Keep large meshes, case/data files, chemistry tables, and result fields out
  of Git. Reference immutable assets by URI and SHA-256.
- Permit typed partial mutation layers over hash-locked Fluent checkpoints.
  Require precision for declared state, but do not require exhaustive ownership
  or reconstruction of inherited solver state.
- Never hard-code personal SCNET paths into reusable case definitions.
- Keep orchestration facts, current numerical/scientific judgments, and human
  review separate. There is no mandatory universal acceptance or promotion
  contract; absent judgments remain `not_evaluated`.
- Agents may explore changes across in-scope Fluent settings. Record every
  mutation, rationale, observation, and artifact so an engineer can inspect and
  continue the evolving investigation.
- The engineer defines the current, versioned investigation objective. It may
  be qualitative or reference selected experimental evidence; do not silently
  turn it into a universal acceptance gate.
- Agent mutation authority includes geometry, meshing controls, and mesh
  topology. Preserve geometry/mesh provenance, units, coordinates, named
  regions, checks, and downstream compatibility evidence.
- Retain failed and rejected candidate attempts as first-class compact records.
  Agents may promote candidates with an attributable reason and recoverable
  predecessor; promotion does not require a universal gate.
- Interrupt the engineer when a choice materially changes physical
  interpretation, geometry/mesh intent, or resource commitment. The detailed
  collaboration UI is future work; do not invent it in the initial backend.
- Tests must run without Fluent by using a recording/fake adapter.
- Keep examples honest about readiness and known blockers.

## Concurrent work ownership

- Schema workers own `src/fluent_case_layer/schema/`, `schemas/`, `case/`, and
  schema-focused tests.
- Driver workers own `src/fluent_case_layer/driver/`, CLI/runner scripts, and
  driver-focused tests.
- Case-documentation workers own `examples/` and `docs/case-catalog.md`.
- The root agent owns root project files, integration, CI, releases, and Lark.

Do not rewrite another worker's files without coordinating first.
