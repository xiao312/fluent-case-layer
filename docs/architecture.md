# Architecture

## Outcome

`fluent-case-layer` is a Fluent/PyFluent-only system for the internal CFD
simulation team. It turns a version-controlled directory of engineering intent
into a deterministic execution plan, reconciles that plan against an observed
Fluent session, and preserves enough evidence to explain every mutation.

OpenFOAM inspired the filesystem ergonomics, but is not a supported solver or
adapter target. The architecture can model Fluent concepts directly rather
than paying for a solver-neutral abstraction that the product does not need.

It deliberately does not pretend Fluent is stateless. Reading a checkpoint,
enabling a model, importing chemistry, creating registers, and patching fields
can change both solver state and the available settings tree. The implementation
therefore behaves as an intent compiler and state reconciler rather than a YAML
serializer.

## Core records

### CaseSpec

The aggregate of the authored `constant/`, `0/`, `system/`, `platforms/`, and
`assets.lock.yaml` files. It contains semantic intent and immutable asset
identities, not machine-local paths or generated solver state. A case may be a
full construction recipe or a partial mutation layer over a hash-locked Fluent
case/data checkpoint; it owns only the state it declares.

### Plan

A canonical, versioned sequence/DAG of typed actions produced for a Fluent
version adapter and platform profile. Planning resolves defaults, units, asset
references, stage dependencies, resource classes, capability requirements,
and expected observations. The canonical JSON representation is hashed before
execution.

### ObservedState

A normalized, necessarily partial snapshot of the Fluent state visible to the
adapter. It is captured around reconciliation so users can distinguish
declared, observed, inherited, defaulted, and solver-induced state. Unknown or
uninspected state is represented as such; it is not silently treated as an
adapter default.

### RunRecord

The append-only evidence envelope: plan hash, environment, scheduler identity,
events, snapshots, checkpoints, artifact hashes, monitor samples, optional
case-local judgments, and human review notes.

### EngineeringObjective

A versioned statement authored by an engineer that defines what the current
investigation is trying to improve. It may remain qualitative or identify
specific monitors and immutable experiment/reference assets to match. It is a
search objective, not a universal pass/fail contract, and a later attempt may
refer to a revised objective.

### CandidateAttempt

One immutable combination of baseline identity, objective revision, candidate
overlay, rationale, compiled plan, and run evidence. Success, failure,
rejection, and promotion are lifecycle facts recorded without deleting the
attempt. An agent or engineer may promote a candidate with an attributable
reason; promotion advances a recoverable reference rather than erasing its
predecessor.

## Compilation and execution

```text
split YAML files
      │ load + type/units validation
      ▼
   CaseSpec ── capability check ──► canonical Plan + SHA-256
                                        │
                         inspect target │ session/checkpoint
                                        ▼
                                  ObservedState
                                        │ semantic diff
                                        ▼
                              staged reconcile/apply
                                        │
                       postconditions + gates + writes
                                        ▼
                                   RunRecord
```

Planning is license-free. Applying can use a recording adapter in tests or the
PyFluent adapter in an allocated Fluent environment.

## Baseline implementation boundary

As of 2026-08-29, the repository implements the strict split-document loader,
cross-file reference checks, versioned non-enforcing engineering objectives,
full-definition and checkpoint-overlay state ownership, canonical plan compiler
and hash, candidate overlays, retained attempt/decision records, recording
adapter, adapter-authorized resume, hash-chained event ledgers, snapshots,
manifests, structural state diff, and bounded multi-case campaign expansion.
All of those paths run without Fluent.

Checkpoint overlays may leave most baseline state inherited. Declared source
pointers are validated, and a whole-section reconcile fails closed unless the
overlay owns the corresponding document root. Mutation below that granularity
still needs path-scoped adapter reconciliation; the current compiler does not
pretend narrow ownership can authorize a broad write.

The PyFluent adapter is deliberately narrower. It can lazily launch or attach,
verify local locked assets, read supported inputs, execute explicit settings
operations, perform a simple hybrid initialization, iterate or advance time,
write checkpoints, and run audited TUI escapes. A high-level mapping from every
typed physics/material/chemistry/boundary/monitor object to the Fluent 2026 R1
settings tree is not yet implemented. The adapter raises a mapping error for
such stages rather than silently doing nothing or applying a partial fallback.

Resume is adapter-authorized. The recording adapter accepts an explicitly
labeled, evidence-only simulated rehydration from the event ledger. A fresh
PyFluent adapter rejects a ledger with completed actions until a
checkpoint/session rehydration contract can prove the solver state; it never
skips setup merely because an event says that setup succeeded earlier.

Before adapter mutation, declared output templates are rendered beneath the
run directory and checked against traversal or unsupported placeholders. A
real `artifact_exists` gate requires a materialized local file and recomputed
SHA-256 matching the manifest; a declaration alone is insufficient.

The recording adapter proves orchestration behavior only. It labels asset
availability as simulated, does not claim content verification, leaves absent
solver gates `not_evaluated`, and never promotes a checkpoint on unknown
evidence.

SCNET Slurm submission, environment activation, remote asset materialization,
Fluent Meshing, FGM construction, DPM injection mapping, UDF compilation, and
case-specific field postprocessing remain explicit platform/adapter work. See
`docs/scnet-platform.md` and the example migration notes.

## Typed stage actions

The initial action vocabulary is intentionally small:

- resolve/read an immutable mesh or checkpoint;
- inspect/capture solver state;
- reconcile models, materials, chemistry, boundaries, and numerics;
- initialize, create a register, or patch a field;
- iterate a steady solver or advance physical time;
- sample monitors and evaluate gates;
- write a checkpoint and attach the evidence available at that moment;
- optionally assign a case-local working role to a checkpoint;
- run an explicit TUI escape with declared reason and postcondition.

Actions declare dependencies, input/output artifact roles, preconditions,
postconditions, retry semantics, and whether resumption may skip a previously
successful action. Side-effecting actions must be observable through the event
stream.

## Solver adapters

The core depends on a narrow Fluent adapter protocol. A Fluent 2026 R1 adapter
maps semantic intent to the PyFluent settings API and captures normalized
observed state. Version-specific paths belong inside adapters, not case files.

TUI is not forbidden, because some Fluent operations lack stable settings API
coverage. Every TUI action must record:

- why it is necessary;
- the supported Fluent version/capability;
- the exact command and redacted arguments;
- its precondition and expected observable postcondition.

There is intentionally no OpenFOAM adapter contract or solver-neutral physics
model. Historical OpenFOAM work may inform campaign expansion, file layout,
and evidence design only.

## Campaigns

A campaign expands explicit case references and overlays into independent plan
instances. Scheduling respects the stage DAG inside each instance and global
limits across instances. Platform profiles define queue, ranks, memory,
walltime, environment entrypoints, and data-locality rules; case physics never
contains personal SCNET paths.

The expansion itself is locked and hashed. Resume operates on that expansion,
so adding a case or changing a matrix cannot silently alter an active campaign.

## Audit layout

```text
.fluent-case/
├── attempts/<attempt-id>.json
├── plans/<plan-sha256>.json
├── decisions.jsonl
├── refs/
│   ├── manifest.json
│   └── objects/<attempt-sha256>.json
└── runs/<attempt-id>/
    ├── plan.lock.json
    ├── run.meta.json
    ├── run-summary.json
    ├── events.jsonl
    ├── snapshots/
    │   ├── <stage>.attempt-001.before.json
    │   └── <stage>.attempt-001.after.json
    ├── checkpoints.manifest.json
    └── artifacts.manifest.json
```

Ordinary non-candidate applies may instead use an explicitly selected run
directory. The candidate store makes plan objects content-addressed, retains
failed records, and treats the decision ledger as authoritative; the named-ref
manifest can be rebuilt after an interrupted derived update.

Large solver artifacts remain in SCNET/object storage. Git stores their logical
roles, URIs, sizes, SHA-256 digests, compatibility metadata, and the commands
needed to resolve them.

## Evidence and judgment stay separate

The layer never collapses the following into one universal `success` boolean:

- orchestration: did the requested stages execute?
- asset readiness: were all immutable inputs present and compatible?
- numerical health: convergence, stationarity, boundedness, conservation;
- scientific validation: comparison against case-specific evidence;
- publication readiness: are provenance and curated artifacts complete?

These axes are case-local and may be revised or left `not_evaluated`; they are
not mandatory global acceptance gates. A Fluent process exiting zero can
therefore coexist with an unresolved or adverse engineering judgment without
corrupting the execution record. Human review is a first-class continuation of
the investigation rather than a final fixed gate.

## Agent mutation model

The agent may explore changes across Fluent physics, models, chemistry,
materials, boundary and initial conditions, numerics, and execution procedure.
Its scope also includes geometry, Fluent Meshing controls, and mesh topology,
provided provenance, units, coordinates, named regions, mesh checks, and
downstream compatibility remain auditable.
The architecture does not encode a fixed approval split between “safe
numerics” and “unsafe physics.” It does require each mutation, rationale,
observation, and resulting artifact to remain attributable and replayable.

Because “make the simulation better” has no context-free objective, each
investigation carries a current, revisable case-local objective or human
judgment. Selecting candidates, overwriting canonical intent, geometry/mesh
authority, and interaction cadence remain workflow decisions rather than
hidden adapter behavior.

The engineer owns the current objective. The agent may promote a candidate,
but must interrupt rather than silently choose when alternatives materially
change physical interpretation, geometry/mesh intent, or resource commitment.
The detailed collaboration UI is deferred; the durable objective, attempt, and
decision records are implemented first.

Failed and rejected attempts remain first-class fixtures for diagnosis,
regression, and later agent evaluation. Storage policy may expire large raw
fields, but not the compact overlay, objective reference, rationale, outcome,
and evidence index.

## Open decisions

The collaboration UI, detailed interrupt/resume protocol, overlay precedence,
campaign failure policy, storage-retention classes, and the first production
replay remain open. See the [design interview](design-interview.md).
