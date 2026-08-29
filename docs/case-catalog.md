# Case catalog

Inventory date: 2026-08-29.

This catalog is an implementation inventory, not a claim that every case is
scientifically validated. It deliberately records three independent states:

- **definition**: whether the inputs are sufficient to construct or continue a
  run;
- **execution**: whether retained evidence shows that Fluent or the reference
  solver actually ran;
- **science**: the current case-specific engineering judgment supported by
  retained physical and numerical evidence; that judgment may include optional
  gates, reference comparisons, and human review.

The provenance paths below use two logical source roots so this repository does
not encode a developer's home directory or an SCNET account path:

```text
CFD_AGENT_BENCH_ROOT = cfd-agent-bench repository
DFODE_PLUGS_ROOT      = dfode-plugs repository
```

The source repositories remain authoritative for historical evidence and large
assets. This repository copies only typed intent and immutable hashes.

## Implemented repository examples

| Example | Repository path | State policy | Engineer objective | Translation state | Historical evidence state |
| --- | --- | --- | --- | --- | --- |
| transient 1D H2/air | `examples/transient-1d-h2-air/case/` | `full_definition` | numerical health, flame propagation, and non-enforcing comparison with a locked Cantera simulation profile | schema-valid, plan-compilable, not executed through this layer | source workflow executed 5,000 steps |
| M2 torch igniter | `examples/m2-torch-igniter/case/` | `checkpoint_overlay`; only two registers and two `premixc` patches are owned | investigate persistent wall thermal/shear risk without assuming a ranking | schema-valid, plan-compilable, not executed through this layer; broader checkpoint state is inherited and observed | source checkpoint continuation executed to iteration 2,500; science pending |
| effusion DRM19 FGM | `examples/effusion-drm19-fgm/case/` | `full_definition` | staged FGM/DPM behavior and non-enforcing comparison with retained tutorial simulation evidence | schema-valid declaration plan; real apply blocked on typed meshing and detailed FGM/DPM adapters | source tutorial executed 300 cold plus 400 reacting iterations and passed 42 setup assertions |

`examples/campaign.yaml` compiles the three together. Compilation or use of the
recording adapter validates plan shape and evidence plumbing only; it does not
resolve assets, launch Fluent, pass numerical gates, or validate science.

Each objective is an attributed, versioned engineering search aim with
`enforcement: none`; it is neither a retroactive validation claim nor an
implicit gate. Agent exploration may promote a candidate with a recorded
reason and recoverable predecessor, but failed and rejected attempts remain
first-class compact evidence. The initial backend defers the rich human-
collaboration UI while still requiring an engineer interruption for choices
that materially alter physical interpretation, geometry/mesh intent, or
resource commitment.

## Status vocabulary

| Dimension | Values used here |
| --- | --- |
| Definition | `runnable`, `surrogate-ready`, `blocked`, `archive-only`, `reference-only` |
| Execution | `executed`, `partial`, `not evidenced` |
| Science | `accepted`, `qualified baseline`, `development only`, `pending`, `blocked`, `not evaluated` |

`Executed` means a solver job completed and left evidence. It does not imply
convergence or physical validity. `Qualified baseline` means a narrower
reproducibility or numerical contract passed; it is not automatically an
experimental validation.

Geometry, meshing controls, and mesh topology are in the eventual agent
mutation scope for Fluent cases. Current adapters must nevertheless fail or
report a mapping gap whenever they cannot preserve and attest geometry source,
units, coordinates, named regions, mesh checks, and downstream compatibility.

## Fluent cases selected for the implementation corpus

| Case | Definition | Execution | Science | Distinct layer features | Provenance |
| --- | --- | --- | --- | --- | --- |
| TUM seven-injector GCH4/GOX | runnable from mesh | partial, plus later development branches | development only | 24.93M-cell mesh import; complete model construction; species inlets; axial wall-temperature profile; named station surfaces; first/second-order branches; pressure and wall-heat-flux gates | `CFD_AGENT_BENCH_ROOT/tasks/fluent-seven-injector-gch4-gox/`; `DFODE_PLUGS_ROOT/recipes/fluent-tum7/` |
| M2 CH4/O2 torch igniter | runnable from case/data checkpoint | executed: iteration 500 to 2500 | pending; residual and PDF-table warnings remain | trusted checkpoint; FGM/PDF assets; ordered cell-register creation and `premixc` patches; patched checkpoint; persistence samples; wall-risk sensitivity branch | `CFD_AGENT_BENCH_ROOT/tasks/fluent-torch-igniter-m2/` |
| 500 N LOX/RP-1 thrust chamber | runnable from several qualified/provisional checkpoints | executed baseline and many development branches | development only under the current contract | checkpoint roles and promotion; partially-premixed FGM; four hollow-cone DPM injections; one-way cold-flow branch; reacting warm start; DPM tracking and fate audits; first-to-second-order promotion; chemistry-table and numerical sensitivities | `CFD_AGENT_BENCH_ROOT/tasks/fluent-lox-rp1-500n/` |
| Transient 1D premixed H2/air | runnable from generated mesh | executed: native routes completed 5,000 steps | qualified native baseline; no external flame experiment claimed | deterministic mesh generation; piecewise equilibrium/reactant initialization; transient `advance_time`; chemistry-backend matrix; callback/UDF hooks; profile sampling | `DFODE_PLUGS_ROOT/recipes/transient-1d-laminar-flame/` |
| Transient 3D premixed H2/air | runnable from generated mesh/restart | executed smoke: native-stiff and precomputed-DFODE paths each completed three steps on 1,048,576 cells and 8 ranks | qualified execution; science not evaluated | 1,048,576-cell structured slab; parallel scaling; same-case backend comparison; restart and rank scaling | `DFODE_PLUGS_ROOT/recipes/transient-3d-premixed-flame/`; `DFODE_PLUGS_ROOT/.work/diagnostics/260821_h2_3d_million_v1/summary.json` |
| Effusion cooling, DRM19/FGM reference | runnable from public tutorial PMDB | executed: 300 cold-flow plus 400 reacting iterations | qualified fixed-iteration tutorial baseline; not fully converged | meshing workflow; periodic pairing; FGM table generation; DPM cone injection and source cadence; cold/reacting stage split; setup assertions; contours | `DFODE_PLUGS_ROOT/recipes/fluent-effusion-drm19/` |
| Effusion cooling, finite-rate mechanism matrix | runnable from the same mesh | executed for global, DRM19 and GRI30 tiers | development-only fixed-work comparison | suite overlays; built-in versus CHEMKIN mechanisms; air initialization repair; reactivity gate; timing matrix | `DFODE_PLUGS_ROOT/recipes/fluent-effusion-drm19/config/finite_rate_matrix.json`; `DFODE_PLUGS_ROOT/reports/archive/effusion-cooling/finite-rate-results-260722.md` |
| Sandia Flame D, steady axisymmetric RANS/EDC | runnable from generated mesh and public TNF profiles | executed for multiple turbulence/EDC branches | development only; archived as not qualified | mesh levels; profile assets; realizable k-epsilon startup; RSM/GEKO branches; EDC/finite-rate chemistry; experimental profile gates and flame-length gate | `DFODE_PLUGS_ROOT/recipes/fluent-sandia-flame-d/`; `DFODE_PLUGS_ROOT/reports/archive/sandia-flame-d/` |
| Sandia Flame D, transient GEKO URANS | runnable from a developed restart | executed for mesh-adaption and backend studies | qualification workflow, not a scientific pass | iterative transient/PISO; 36k-cell base plus native PUMA 5x/10x adaption; 32 ranks; matched DI/DFODE checkpoint; fixed tier promotion; pointwise chemistry sampling | `DFODE_PLUGS_ROOT/recipes/fluent-chemistry-validation-loop/config/sandia_gri30_urans.json`; `DFODE_PLUGS_ROOT/reports/archive/integration/mesh-scaling-benchmark-260810.md` |
| Sandia Flame D, 3D LES | runnable-shape configuration | not evidenced in the tracked recipe | not evaluated | WALE; synthetic inlet turbulence; bounded second-order time; 3D candidate/production mesh tiers; startup-to-production numerical transition; 32/64-rank platform stress | `DFODE_PLUGS_ROOT/recipes/fluent-sandia-flame-d-les/config/les_mesh.json` |
| A60-like planar H2/O2 counterflow | runnable for warm stages | execution artifacts referenced by the run ledger | development only | 6 MPa Peng-Robinson mixture; 12,288-cell generated mesh; `warm_a1000 -> warm_a2000` restart continuation; intentionally disabled 85 K stage with a typed blocker | `DFODE_PLUGS_ROOT/recipes/fluent-a60-counterflow/` |
| MASCOTTE A60 LOX/GH2 axisymmetric surrogate | surrogate-ready | cold and reacting smoke stacks executed | blocked for production science by LOX-property error | generated axisymmetric mesh; transcritical inlet; Peng-Robinson audit; cold-before-reacting gate; H2/O2 CHEMKIN mechanism | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/mascotte/mascotte_a60.json`; `.../mascotte/WORKFLOW.md` |
| MASCOTTE A60 full-cylinder development model | surrogate-ready | not evidenced | not evaluated | 1M/3M/6M mesh ladder; transient SST; first-order startup then second-order; mapped/developed-checkpoint requirement | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/mascotte/mascotte_a60_3d360.json`; `.../mascotte/A60_3D360.md` |
| MASCOTTE G2 LOX/GCH4 axisymmetric surrogate | surrogate-ready | cold and reacting smoke stacks executed | blocked for production science pending the real-fluid ladder | case matrix with A60; GRI-Mech 3.0; dense-fluid audit; cold-before-reacting gate | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/mascotte/mascotte_g2.json`; `.../mascotte/WORKFLOW.md` |
| Mayer Case 3 transcritical N2 jet | surrogate-ready | API/mesh workflow present; quantitative run not evidenced | pending | pure-fluid NIST versus Peng-Robinson model branch; pseudo-boiling property gate; nonreacting precursor for rocket cases | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/mayer/` |

### Historical benchmark evidence

The August benchmark attempts are repair and configuration variants of TUM7,
M2, and Rocket 500N; they are not new physical cases. Preserve them as an
agent-debugging corpus for failure classification, recovery planning, and plan
diff tests. The retained August corpus contains **46 native Fluent attempts**:
28 Rocket 500N, 10 M2, and 8 TUM7. Of those, 38 are marked completed by the
harness. Harness completion records terminal orchestration and is not a claim
of numerical convergence or scientific acceptance. The task benchmark files,
native run ledgers, and publication snapshot under
`CFD_AGENT_BENCH_ROOT/tasks/fluent-{lox-rp1-500n,torch-igniter-m2,seven-injector-gch4-gox}/`
are the provenance for those counts and statuses.

Representative failure modes include:

- invalid PyFluent settings paths and TUI fallbacks;
- a wall profile mapped to the wrong coordinate;
- incompatible or out-of-range PDF/FGM states;
- incomplete DPM tracking and stale source terms;
- first-to-second-order transitions that destabilize a restart;
- runs that finish operationally but fail mass closure, stationarity, or
  experimental comparison gates.

## OpenFOAM campaign reference (historical pattern only)

| Case | Definition | Execution | Science | Why it belongs in this project | Provenance |
| --- | --- | --- | --- | --- | --- |
| Five private injector geometries, `g01`-`g05` | reference-only; not a supported case in this repository | an end-to-end five-case campaign was executed historically; the benchmark manifest remains `draft` | solver completion only; no cross-geometry scientific validation claimed | reusable orchestration pattern: one template plus five immutable geometry overlays, independent DAGs, bounded concurrency, shared scripts, and per-item evidence | `CFD_AGENT_BENCH_ROOT/tasks/injector-five-stl/` |

This is an orchestration reference only. The product supports Fluent/PyFluent;
an OpenFOAM adapter and solver-neutral case model are explicitly out of scope.

## Blocked and archive-only physical cases

These definitions are useful because a typed layer must be able to reject or
hold a campaign before consuming solver licenses.

| Case | Definition | Blocking evidence, judgment, or input | Provenance |
| --- | --- | --- | --- |
| MASCOTTE C60 | blocked | no complete reproducible mesh/operating-condition package in the current catalog | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/mascotte/mascotte_c60.json` |
| DLR BKN LOX/H2 | blocked | nozzle/inlet geometry and boundary details are incomplete | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/dlr-bkn/dlr_bkn_lox_h2.json` |
| NASA GOX/GH2 multi-element combustor | archive-only | public dimensions do not support a faithful axisymmetric model; a 3D sector still lacks geometry and selected-run conditions | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/nasa-gox-gh2/nasa_gox_gh2.json` |
| TUM circular GOX/GCH4, O/F 2.6 | blocked | mass flows, full nozzle profile, wall-temperature profile and tabulated validation data are absent | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/tum/tum_gox_gch4_of26.json` |
| TUM circular GOX/GH2, O/F 5.9 | blocked | same geometry/flow/validation gaps as the methane point | `DFODE_PLUGS_ROOT/recipes/fluent-rocket-validation/cases/tum/tum_gox_gh2_of59.json` |

A blocked case should compile to a diagnostic plan but must not reach a
license-consuming `apply` stage unless its blockers are resolved explicitly.

## Supporting workflows, not additional physical cases

| Workflow | Reusable feature | Provenance |
| --- | --- | --- |
| CFD-conditioned state export | deterministic HDF5 field extraction, species-order provenance and sampling strata | `DFODE_PLUGS_ROOT/recipes/fluent-cfd-conditioned-data/` |
| Chemistry backend comparison | same-restart native DI/CHEMKIN/callback matrix; separates local chemistry maps from coupled solver behavior | `DFODE_PLUGS_ROOT/recipes/fluent-chemistry-backend-comparison/` |
| Persistent Fluent native labeler | repeated independent-cell shards, fail-closed backend settings, resident session, native-target provenance | `DFODE_PLUGS_ROOT/recipes/fluent-chemistry-validation-loop/native-labeler/` |
| Single-cell, total-enthalpy, same-input and JVP gates | fast component tests for chemistry adapters and evidence contracts | `DFODE_PLUGS_ROOT/recipes/fluent-chemistry-validation-loop/` |
| `internal-cfd-001` | benchmark-template fixture only; its QoI and units are placeholders | `CFD_AGENT_BENCH_ROOT/tasks/internal-cfd-001/` |
| Phoenix 500 N design workflow | useful five-stage DAG and provenance reference, but it is a multiphysics engine-design task rather than a Fluent case | `CFD_AGENT_BENCH_ROOT/tasks/phoenix-rocket-500n/` |

## Recommended execution order (not case tiers)

1. **Compile-only:** all three repository examples, including asset and DAG
   validation without Fluent.
2. **Small fresh construction:** transient 1D H2/air.
3. **Restart mutation:** M2 register/patch/continuation smoke.
4. **Multi-stage construction:** effusion mesh, FGM, DPM, cold and reacting
   stages.
5. **Medium physics:** Sandia RANS/URANS and A60 counterflow.
6. **Large restart/campaign:** TUM7, Rocket 500N, and Sandia LES.

All Fluent cases exercise the same semantic product tier. This order reflects
compute cost, data size, and debugging risk only: the first three steps cover
principal state transitions at modest cost, while later cases stress
scalability and recovery rather than define a separate advanced API.
