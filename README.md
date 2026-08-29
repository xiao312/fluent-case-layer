# Fluent Case Layer

An OpenFOAM-inspired, typed, staged, and auditable case layer for ANSYS
Fluent/PyFluent. It keeps simulation intent in reviewable YAML, compiles that
intent into a deterministic action DAG, and records what an adapter actually
did.

This is the first development baseline. Schema validation, planning,
recording-adapter execution, evidence capture, and multi-case campaign
expansion work without Fluent. The real PyFluent adapter supports a narrow set
of explicit operations and fails closed when a semantic mapping is missing;
the three provenance-backed examples have not yet been replayed through this
new layer on SCNET.

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
cross-file reference errors fail before a solver license is requested. Twelve
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
| Schema | strict split YAML, units, selectors, assets, physics, chemistry, boundaries, initialization actions, monitors/gates, stage DAG, platforms |
| Compiler | stable dependency order, canonical JSON projection, case/plan hashes, typed campaign-overlay revalidation |
| Executor | retries, adapter-approved resume, immutable plan lock, safe run-root outputs, before/after/failure snapshots, independent status axes |
| Evidence | append-only hash-chained events, artifact/checkpoint manifests, snapshot diff |
| Recording adapter | deterministic license-free state transitions for tests and agent evaluation |
| PyFluent adapter | lazy launch/attach, locked local-asset verification, explicit settings operations, simple hybrid initialization, solve/time advance, checkpoints, audited TUI |
| Campaigns | multiple cases, variants/matrices, portable campaign hashes, bounded concurrency, failure isolation |

The CLI surface is:

```text
fluent-case validate <case>
fluent-case plan <case>
fluent-case apply <case> [--adapter recording|pyfluent]
fluent-case snapshot <case>
fluent-case diff <before.json> <after.json>
fluent-case campaign <campaign.yaml> [--mode validate|plan|apply]
```

Repository-checkout wrappers are also provided in [`scripts/`](scripts/).

## Example corpus

| Example | Historical source evidence | Status in this repository |
| --- | --- | --- |
| [`transient-1d-h2-air`](examples/transient-1d-h2-air/) | native routes completed 5,000 transient steps | typed migration; SCNET replay pending |
| [`m2-torch-igniter`](examples/m2-torch-igniter/) | checkpoint continued from iteration 500 to 2,500 | typed migration; science gates still pending |
| [`effusion-drm19-fgm`](examples/effusion-drm19-fgm/) | tutorial workflow ran 300 cold-flow + 400 reacting iterations | typed intent; meshing/FGM/DPM mappings pending |

[`examples/campaign.yaml`](examples/campaign.yaml) compiles the three together.
The wider inventory documents TUM7, Rocket 500N, transient H2, effusion,
Sandia, MASCOTTE, Mayer, blocked cases, and the five-geometry OpenFOAM
campaign—without conflating solver execution with numerical or scientific
acceptance. See the [case catalog](docs/case-catalog.md) and [migration
notes](docs/example-migration-notes.md).

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
manifests. Orchestration, numerical health, and scientific validation remain
separate statuses: a Fluent process exiting normally is not a scientific pass.

See [architecture](docs/architecture.md), [contributing](CONTRIBUTING.md), and
the [design interview](docs/design-interview.md). Project progress and weekly
logs are maintained in the private Lark document
[CFD Agent｜Fluent 算例层与调试智能化](https://qcnwovvb1xop.feishu.cn/docx/NBNJdruXgolpXUxS1qoczNmKnBH).
