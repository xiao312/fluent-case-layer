# SCNET platform contract

Inventory date: 2026-08-29.

The case format keeps physics independent of a particular SCNET account. The
checked-in profiles describe resource intent and refer to runtime values by
environment variable; they do not contain a developer home directory, token,
or scheduler account.

## Checked-in profiles

| Profile | Intended use | Resource intent | Status |
| --- | --- | --- | --- |
| `scnet-cpu-small` | validation, fresh small cases, restart smoke tests | 1 node, 4 ranks, 4 tasks/node, 32 GiB, 1 hour | development default |
| `scnet-cpu-64r` | large meshes and scaling qualification | 2 nodes, 64 ranks, 32 tasks/node, 128 GiB/node, 12 hours | development |
| `scnet-dcu` | future accelerator qualification | 1 node, 1 rank, 1 accelerator, 64 GiB, 1 hour | disabled |

Recent retained workflows also exercised 8 ranks for the 1,048,576-cell H2/air
3D smoke and 32/64-rank tiers for larger Sandia and rocket-development work.
Those observations motivate the profiles; they are not proof that every case
scales efficiently at the selected rank count.

## Runtime bindings

The profiles target Fluent 2026 R1 and a matching PyFluent environment. The
operator or future scheduler adapter supplies these variables at runtime:

| Variable | Meaning |
| --- | --- |
| `SCNET_FLUENT_2026_ENV` | site-provided Fluent 2026 R1 environment setup script |
| `SCNET_PYFLUENT_VENV` | Python environment containing the matching PyFluent release |
| `SCNET_CPU_PARTITION` | current CPU partition; recently this has been `kshcnormal` |
| `SCNET_SLURM_ACCOUNT` | scheduler account, when required |

Recent server entrypoints required a glibc 2.31-compatible execution
environment. Treat that as runtime compatibility evidence, not as portable
case physics.

Case-local asset roots use separate variables such as `FCL_M2_ASSET_ROOT`.
Each referenced file still has to match its locked SHA-256 before the real
adapter may load it.

## Current boundary

The first scaffold compiles platform profiles into deterministic launch intent
and can launch or attach through PyFluent inside an already prepared
allocation. It does not yet submit Slurm jobs, source the named setup script,
activate the named Python environment, materialize remote assets, or negotiate
licenses. Those belong to a platform adapter and must fail closed until
implemented.

DCU execution remains disabled until the selected Fluent release, models, and
evidence collectors are qualified on that hardware. A CPU run and a DCU run
must never be treated as interchangeable merely because their case intent is
the same.

## Evidence interpretation

Resource allocation, process exit, numerical health, and scientific validity
are separate claims. A successful Slurm/PyFluent invocation establishes only
execution evidence. A case may declare monitors, references, and gates when
they help answer its engineer-defined objective, but no universal numerical or
scientific gate is required; absent judgments remain `not_evaluated`.
