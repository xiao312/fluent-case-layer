# Example migration notes

The examples are typed translations of existing workflows, not byte-for-byte
copies. No mesh, case/data, PDF/FGM table, licensed tutorial archive, result
field, personal account path, or credential is stored here.

## Common translation

| Existing concern | New case file |
| --- | --- |
| solver, dimensionality and physical models | `constant/physics.yaml` |
| material definitions and cell-zone assignment | `constant/materials.yaml` |
| chemistry mechanism, model and stream composition | `constant/chemistry.yaml` |
| desired initial fields | `0/fields.yaml` |
| named-zone boundary intent | `0/boundary-conditions.yaml` |
| schemes, coupling and relaxation | `system/numerics.yaml` |
| ordered initialize/register/patch actions | `system/initialization.yaml` |
| residuals, QoIs and optional case-local judgments | `system/monitors.yaml` |
| versioned, attributed, non-enforcing investigation aim | `system/objectives.yaml` |
| explicitly owned, inherited and observed Fluent state | `system/state.yaml` |
| typed stage DAG, retries and checkpoints | `system/control.yaml` |
| Slurm/runtime choices | `platforms/*.yaml` |
| immutable external binaries and provenance | `assets.lock.yaml` |

The split is semantic. A compiler may merge the files into one immutable run
plan, but it must retain file/field provenance so a plan diff points back to a
user-authored value.

`full_definition` means the layer owns the listed fresh-case paths and leaves
undeclared values at Fluent defaults. `checkpoint_overlay` means all undeclared
state is inherited from an exact hash-locked case/data baseline; only a path
with a real staged mutation is declared as owned. Broader observations may
surround a narrow mutation for compatibility evidence. The current driver
cannot authorize a narrow overlay through a whole-document reconcile, so it
fails closed rather than silently expanding mutation authority.

Objectives remain separate from gates. An objective may name qualitative
questions or reference immutable experimental, analytical, or simulation data,
but `enforcement: none` prevents it from becoming an automatic acceptance
decision. A case-local gate is a separately authored judgment. Neither an
objective match nor a solver completion alone establishes scientific validity.

Agent exploration retains successful, failed, and rejected candidates as
compact attributable records. An agent may promote a candidate with a reason
and a recoverable predecessor; a universal pass gate is not required. Geometry,
meshing controls, and topology are within eventual mutation authority, although
the initial adapters must expose unsupported geometry/meshing operations as
mapping gaps. Detailed human-collaboration UI is deferred; consequential
physics, geometry, or resource decisions still interrupt the engineer.

## Transient 1D H2/air

Source: `DFODE_PLUGS_ROOT/recipes/transient-1d-laminar-flame/`.

Features retained:

- a `full_definition` state policy over the fresh mesh and authored solver
  setup;
- 1,000-cell quasi-1D mesh intent and H2/O2/N2 mixture;
- 101325 Pa, 300 K unburned state and adiabatic energy;
- H2/O2 mechanism with 10 species and 29 reactions;
- piecewise equilibrium/reactant initialization;
- `5e-7 s` timestep, 5,000 steps and 20 outer iterations per step;
- a hash-locked Cantera FreeFlame simulation profile used by a non-enforcing
  model-reference objective;
- four-rank small platform and an explicit final evidence/checkpoint contract.

Migration gaps:

- the deterministic generated mesh is a locked input asset; regenerating and
  attesting it still needs a typed preprocessing action;
- regenerating the locked Cantera equilibrium/FreeFlame reference still needs
  a typed preprocessing action and provenance attestation;
- the source's 50-step profile cadence needs a typed periodic-sampling policy;
- backend overlays (native stiff, CHEMKIN, CVODE and DFODE) should use the
  landed campaign matrix rather than edits to the base case;
- UDF compilation/loading needs a typed extension action and binary hash.

## M2 torch igniter

Source: `CFD_AGENT_BENCH_ROOT/tasks/fluent-torch-igniter-m2/`.

Features retained:

- immutable iteration-500 case/data plus FGM/PDF table assets as a
  `checkpoint_overlay` baseline;
- observed compatibility expectations for the inherited 2 MPa nominal point,
  pure CH4/O2 streams, models, tables, fields, and numerical methods;
- restart audit before mutation;
- two ordered cylindrical registers, `premixc` patching, and an intermediate
  patched checkpoint;
- 2,000-iteration continuation and persistence sampling;
- an open, non-enforcing wall-risk investigation with no assumed wall ranking;
- separate operational, reacting-state and numerical-health checks.

Migration gaps:

- the two exact register geometries and patch order are from the verified
  smoke branch (89,725 and 47,542 selected cells); production execution must
  still compare resolved cell counts and hold on drift;
- the driver needs cell-count evidence after each register and patch;
- path-scoped settings reconciliation is required before pressure, boundary,
  or numerical-method differences can become declared overlay mutations; the
  current example only observes them and must hold on drift;
- Fluent PDF-table range warnings need typed counters rather than transcript
  text matching alone;
- wall percentile statistics and localization currently require a field-data
  postprocessor action;
- a fixed-wall sensitivity should be a campaign overlay, not a mutation of the
  adiabatic baseline.

## Effusion cooling DRM19/FGM

Source: `DFODE_PLUGS_ROOT/recipes/fluent-effusion-drm19/`.

Features retained:

- a `full_definition` state policy including geometry and meshing intent;
- public tutorial PMDB referenced by its real SHA-256;
- meshing and periodic-zone intent;
- nonadiabatic partially premixed FGM at 1,519,875 Pa;
- 300-stream hollow-cone DPM injection and 50-iteration source cadence;
- explicit `mesh -> FGM -> reconcile -> cold -> ignite -> reacting -> evidence`
  DAG with durable checkpoints;
- tutorial setup assertions and reactivity/field evidence;
- cleaned, locked tutorial simulation ranges used by a non-enforcing liner
  temperature comparison objective rather than duplicated scientific gates.

Migration gaps:

- the initial driver must distinguish Fluent Meshing from Solver sessions;
- FGM table calculation/write/read needs a typed action with Fluent-version
  capability checks;
- periodic pairing, perforation definitions and DPM source updates need
  stable settings adapters or declared TUI escapes;
- stage resume must verify hashes and observed solver state before accepting a
  checkpoint;
- the finite-rate global/DRM19/GRI30 matrix should be expressed as campaign
  overlays after its mechanism-specific fields have stable schema paths.

## Deferred large-case mappings

### TUM7

Map the mesh, operating-point YAML, experimental observations and wall profile
into four locked assets. Compile setup into distinct model, boundary, profile,
station-surface, first-order, second-order and evidence stages. The required
new schema features are profile coordinate/units, derived report surfaces,
experiment-target datasets and large-asset locality constraints.

### Rocket 500N

Represent each supplied checkpoint as an asset with a role and qualification
state: historical reacting, qualified one-way cold, provisional reacting warm
start, and promoted second-order continuation. The required new schema
features are checkpoint promotion transactions, DPM source epochs, complete
particle fate accounting, numerical-scheme audits, chemistry-table
compatibility and steady-window gates.

### Five-geometry OpenFOAM historical reference

Retain only the reusable orchestration lessons: one suite with five immutable
geometry bindings, independent per-item DAGs, bounded cross-item execution,
and per-case artifact manifests. The product is Fluent-only; these OpenFOAM
cases are not migration targets and do not require an adapter boundary here.

## Audit artifacts expected from every example

```text
runs/<run-id>/
  plan.lock.json
  run.meta.json
  run-summary.json
  events.jsonl
  snapshots/<stage>.attempt-<nnn>.before.json
  snapshots/<stage>.attempt-<nnn>.after.json
  artifacts.manifest.json
  checkpoints.manifest.json
```

The executor resolves every stage `path_template` beneath the driver run
directory before adapter mutation. Artifact and checkpoint manifests index the
result; real artifact gates require a materialized local file whose recomputed
SHA-256 matches its manifest entry. Every TUI escape must add its reason,
Fluent-version constraint, exact command and expected postcondition to
`plan.lock.json` and `events.jsonl`.
