# Repository working agreement

## Product intent

Build a solver-aware configuration compiler and state reconciler for Fluent,
not a collection of opaque automation scripts. User-authored case files must
remain readable, typed, versionable, and independent of machine-local paths.

## Engineering rules

- Prefer PyFluent settings API operations; explicit TUI escapes must record a
  reason, Fluent-version constraint, exact command, and expected postcondition.
- Separate desired case intent, compiled plan, observed Fluent state, and run
  evidence.
- Treat stages as a dependency graph with typed inputs, outputs, preconditions,
  postconditions, retries, gates, and checkpoint promotion.
- Keep large meshes, case/data files, chemistry tables, and result fields out
  of Git. Reference immutable assets by URI and SHA-256.
- Never hard-code personal SCNET paths into reusable case definitions.
- Distinguish orchestration success, numerical health, and scientific
  validation status.
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
