# Fluent Case Layer

An OpenFOAM-inspired, typed, staged, and auditable case layer for ANSYS
Fluent/PyFluent. It keeps simulation intent in reviewable YAML, compiles that
intent into a deterministic action DAG, and records what an adapter actually
did. The filesystem idea is the inspiration; this is a Fluent-only product and
does not plan to support OpenFOAM.

This is the first development baseline. Schema validation, planning,
recording-adapter execution, objective-driven candidate attempts, evidence
capture, and multi-case campaign expansion work without Fluent. The real
PyFluent adapter supports a narrow set of explicit operations and fails closed
when a semantic mapping is missing; the three provenance-backed examples have
not yet been replayed through this new layer on SCNET.

## Why this layer exists

PyFluent is an imperative, stateful API. Fluent settings also depend on what
mesh/checkpoint has been loaded and which models are already active. Treating a
Python script as the case definition makes review, reuse, diffing, and repair
harder than they are for OpenFOAM dictionaries.

This project borrows the useful filesystem idea without pretending Fluent is
stateless:

```text
authored CaseSpec -> canonical Plan + SHA-256 -> adapter mutations
                                               -> observed snapshots
                                               -> hash-chained RunRecord
```

The authored files declare desired physics and the order-sensitive stage graph.
Version-specific settings paths live behind adapters. Large or licensed inputs
remain outside Git and are referenced by immutable SHA-256 locks.

The target authoring model also supports partial mutation layers over locked
Fluent case/data checkpoints. Such a layer declares what it owns or changes and
labels the rest as inherited or merely observed; it does not need to reconstruct
or allowlist every setting already stored in Fluent. The schema implements both
full definitions and checkpoint overlays, validates source pointers, and refuses
a whole-section reconciliation unless the overlay explicitly owns that whole
document. Finer path-scoped adapter reconciliation remains future work.

Each agent investigation is driven by a versioned, engineer-defined objective,
which may include matching selected aspects of experiment data. Candidate
overlays, failed/rejected attempts, promotion decisions, and their evidence are
retained. Agents may promote candidates and may eventually change geometry and
mesh topology as well as solver state; consequential ambiguity is returned to
the engineer. The richer collaboration interface is intentionally deferred.

## Case layout

```text
case/
├── constant/
│   ├── physics.yaml
│   ├── materials.yaml
│   └── chemistry.yaml
├── 0/
│   ├── fields.yaml
│   └── boundary-conditions.yaml
├── system/
│   ├── numerics.yaml
│   ├── initialization.yaml
│   ├── monitors.yaml
│   ├── objectives.yaml
│   ├── state.yaml
│   └── control.yaml
├── platforms/
│   ├── scnet-cpu-small.yaml
│   ├── scnet-cpu-64r.yaml
│   └── scnet-dcu.yaml
└── assets.lock.yaml
```

The checked-in [`case/`](case/) directory is a complete illustrative template.
Every document uses strict Pydantic models; unknown fields, invalid units,
unresolved assets, impossible zone/cardinality contracts, bad stage edges, and
cross-file reference errors fail before a solver license is requested. Fourteen
generated JSON Schemas are available in [`schemas/`](schemas/).

## Quick start

Python 3.11 or newer is required. Using `uv`:

```bash
uv sync --extra dev
uv run fluent-case validate case --platform scnet-cpu-small
uv run fluent-case plan case --platform scnet-cpu-small \
  --output .fluent-case/example-plan.lock.json
uv run fluent-case apply case --platform scnet-cpu-small \
  --adapter recording --run-dir .fluent-case/example-run
uv run fluent-case campaign examples/campaign.yaml --mode validate
uv run fluent-case campaign examples/campaign.yaml --mode plan
```

Or install into an existing environment with
`python -m pip install -e '.[dev]'`. The recording adapter is a license-free
orchestration simulator: simulated inputs are labeled unverified, missing
solver metrics stay `not_evaluated`, and it cannot promote a checkpoint on
unknown evidence.

## Components

| Component | Current capability |
| --- | --- |
| Schema | strict split YAML, units, selectors, assets, physics, chemistry, boundaries, initialization actions, optional monitors/gates, stage DAG, platforms |
| Objectives and state | versioned non-enforcing engineer objectives; full-definition or hash-locked checkpoint-overlay ownership with declared/observed paths |
| Compiler | stable dependency order, canonical JSON projection, case/plan hashes, typed campaign-overlay revalidation |
| Executor | retries, adapter-approved resume, immutable plan lock, safe run-root outputs, before/after/failure snapshots, independent status axes |
| Evidence | append-only hash-chained events, artifact/checkpoint manifests, snapshot diff |
| Candidate attempts | exact overlay + rationale, objective/state digests, retained success/failure, append-only promote/reject decisions, recoverable named refs |
| Recording adapter | deterministic license-free state transitions for tests and agent evaluation |
| PyFluent adapter | lazy launch/attach, locked local-asset verification, explicit settings operations, simple hybrid initialization, solve/time advance, checkpoints, audited TUI |
| Campaigns | multiple cases, variants/matrices, portable campaign hashes, bounded concurrency, failure isolation |

The CLI surface is:

```text
fluent-case validate <case>
fluent-case plan <case>
fluent-case apply <case> [--adapter recording|pyfluent]
fluent-case candidate plan <case> --overlay <overlay.yaml> --rationale <text>
fluent-case candidate apply <case> --overlay <overlay.yaml> --rationale <text>
fluent-case attempt list|show|decide|rebuild-refs ...
fluent-case snapshot <case>
fluent-case diff <before.json> <after.json>
fluent-case campaign <campaign.yaml> [--mode validate|plan|apply]
```

Repository-checkout wrappers are also provided in [`scripts/`](scripts/).

## Example corpus

| Example | Historical source evidence | Status in this repository |
| --- | --- | --- |
| [`transient-1d-h2-air`](examples/transient-1d-h2-air/) | native routes completed 5,000 transient steps | typed migration; SCNET replay pending |
| [`m2-torch-igniter`](examples/m2-torch-igniter/) | checkpoint continued from iteration 500 to 2,500 | typed checkpoint overlay; deeper engineering review pending |
| [`effusion-drm19-fgm`](examples/effusion-drm19-fgm/) | tutorial workflow ran 300 cold-flow + 400 reacting iterations | typed intent; meshing/FGM/DPM mappings pending |

[`examples/campaign.yaml`](examples/campaign.yaml) compiles the three together.
The wider inventory documents TUM7, Rocket 500N, transient H2, effusion,
Sandia, MASCOTTE, Mayer, and blocked cases. A historical five-geometry OpenFOAM
campaign is retained only as a campaign-orchestration reference, not as a
supported case or adapter roadmap. The catalog does not conflate solver
execution with current numerical or scientific judgment. See the [case
catalog](docs/case-catalog.md) and [migration notes](docs/example-migration-notes.md).

## PyFluent and SCNET boundary

Install `.[fluent]` only in an environment intended to launch or attach to
Fluent. A real adapter run first resolves environment/repository assets and
verifies their bytes against `assets.lock.yaml`. Unmapped semantic reconcile,
register, patch, initialization, or monitor operations raise an explicit
adapter-mapping error instead of succeeding as a no-op.

Event-ledger resume is exercised by the recording adapter. A fresh PyFluent
process currently rejects skipped completed stages until a checkpoint/session
rehydration contract is implemented. Declared outputs are resolved beneath the
run root, and real artifact gates require an existing file whose SHA-256
matches its manifest.

The checked-in SCNET profiles currently compile resource and launch intent;
they do not yet submit Slurm jobs, activate the site environment, materialize
remote assets, or negotiate licenses. The [SCNET platform
contract](docs/scnet-platform.md) records the recent CPU/rank envelope and the
disabled DCU profile.

## Audit output

Each apply run writes an immutable plan lock, run identity/summary,
hash-chained `events.jsonl`, per-stage snapshots, and artifact/checkpoint
manifests. Candidate execution additionally retains the exact overlay,
rationale, objective/state digests, success or failure record, and hash-chained
promotion/rejection decisions. Orchestration facts, evolving case-local
judgments, and human review remain separate: a Fluent process exiting normally
is neither a scientific pass nor a failure by itself, and absent judgments stay
`not_evaluated`.

See [architecture](docs/architecture.md), [contributing](CONTRIBUTING.md), and
the [design interview](docs/design-interview.md). Project progress and weekly
logs are maintained in the private Lark document
[CFD Agent｜Fluent 算例层与调试智能化](https://qcnwovvb1xop.feishu.cn/docx/NBNJdruXgolpXUxS1qoczNmKnBH).
