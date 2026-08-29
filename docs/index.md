# Fluent Case Layer documentation

Fluent Case Layer is a typed, staged, and auditable authoring layer for ANSYS
Fluent through PyFluent. It gives engineers reviewable YAML while preserving
the stateful and version-dependent nature of Fluent.

Start with the [authoring guide](manual/authoring.md), then use the generated
[dictionary reference](reference/index.md) for every accepted key, option,
default, constraint, Fluent concept, PyFluent path, and current adapter status.
Agents should also read the [agent guide](manual/agent-guide.md).

## Documentation guarantees

- Every authored dictionary field is present in the generated reference.
- Static choices come from the same Pydantic models used for validation.
- Fluent/PyFluent mappings have an explicit confidence and implementation status.
- State-dependent PyFluent choices are labeled as runtime-discovered.
- Generated pages and the machine-readable catalog are checked for drift in CI.

The reference targets Fluent 2026 R1. A documented candidate path is not an
implemented adapter operation; consult [coupling coverage](reference/coverage.md)
before applying a case.

## Project guides

- [Authoring cases](manual/authoring.md)
- [Using the reference as an agent](manual/agent-guide.md)
- [Documentation architecture and provenance](manual/documentation-system.md)
- [Runtime option discovery](manual/runtime-discovery.md)
- [Case-layer architecture](architecture.md)
- [SCNET platform contract](scnet-platform.md)
- [Example case catalog](case-catalog.md)
- [Example migration notes](example-migration-notes.md)
- [Design interview](design-interview.md)
