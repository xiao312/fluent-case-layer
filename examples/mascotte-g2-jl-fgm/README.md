# MASCOTTE G2 reduced-JL diffusion-FGM probe

This case keeps two claims separate:

1. A historical reproduction is **blocked**. The audit found no provenance-locked
   G2 Fluent flamelet (`.fla`) or PDF table, and the primary FGM source does not
   report enough Fluent controls to regenerate its table uniquely.
2. An **engineer-selected exploratory setup/readback probe** is defined for
   Fluent 2026 R1. It imports the locked reduced-JL CHEMKIN files, selects the
   partially-premixed diffusion-FGM model, pure G2 streams, finite-rate TCI,
   transported progress-variable variance, beta PDF, automatic Fluent progress
   variable, and exact SRK density. A complete probe is required to serialize
   every active settings group and allowed enum value without calculating
   flamelets, calculating a PDF table, or advancing the flow solution.

The probe deliberately leaves flamelet integration, scalar-dissipation,
adaptation, enthalpy, and PDF-table grid controls at their active Fluent 2026 R1
runtime values. Those complete groups must be read back as evidence. A later
revision must review and freeze every value before any table-generation code may
exist.
The paper's statement of 64-point automatic resolution is retained in the
comparison contract, but is not mapped onto a guessed Fluent node.

Set `MASCOTTE_G2_ASSET_ROOT` to the directory containing `mesh/` and `jl9/` with
the bytes locked in `case/assets.lock.yaml`. Set `MASCOTTE_G2_REFERENCE_ROOT` to
the directory containing the locked digitized OH-star NPZ. The reusable case
contains no machine-specific SCNET path.

`automation/setup_readback_smoke.py` requires an explicit setup-only confirmation
and contains no table-calculation, initialization, or iteration path. Its JSON
result is a discovery artifact, not a table, converged solution, or validation
result.

## Wuzhen setup/readback probe

Two Wuzhen attempts on 2026-08-31 stopped before complete readback. The first
identified a `NamedObject.list()` versus `get_object_names()` discovery bug;
that bug is fixed and the retry progressed past species enumeration. The retry
then failed closed because Fluent returned no allowed-value evidence for the
active PDF option. The setup/readback execution is therefore still blocked,
and no `SUCCESS` artifact exists. See the
[auditable attempt note](reference/wuzhen-setup-readback/README.md) and its
[structured evidence manifest](reference/wuzhen-setup-readback/evidence-manifest.json).

`case/platforms/scnet-wuzhen-setup-readback.yaml` is the bounded CPU profile:
one Fluent rank in a four-CPU, 7 GiB, 20-minute `wzacnormal03` allocation. The
site-specific wrapper is
`automation/submit_wuzhen_setup_readback.sh`. It refuses a dirty or unpushed
revision and submits under Slurm account `ac8azwcnf1`.

The wrapper stages exactly five simulation inputs from the immutable source
revision recorded in `automation/wuzhen-setup-readback-assets.json`: the locked
86,400-cell mesh, three JL9 CHEMKIN files, and digitized relative OH-star data.
The OH-star data is retained as comparison provenance and is not consumed by
the Fluent setup. A separate five-wheel manifest supplies Pydantic v2 to the
proven PyFluent Python 3.11 environment without network access; wheels are
runtime dependencies, not simulation inputs.

Prepare those wheels in a local directory, set `FCL_WUZHEN_WHEELHOUSE` to it,
then run the wrapper from a clean, pushed branch:

```bash
FCL_WUZHEN_WHEELHOUSE=/path/to/locked-wheels \
  examples/mascotte-g2-jl-fgm/automation/submit_wuzhen_setup_readback.sh RUN_LABEL
```

The defaults target the established `ac8azwcnf1-wuzhen` SSH alias and the
hash-locked MASCOTTE source revision. They can be changed with the documented
`FCL_WUZHEN_*` environment variables in the wrapper, but asset bytes must still
match the checked-in contract. A successful run contains
`execution-provenance.json`, `setup-readback.json`, `verification.json`, and
`evidence.sha256`. `SUCCESS` is created only after independent verification of
all artifacts. Failed setup attempts retain structured failure JSON and Slurm
logs and never create `SUCCESS`.

Primary context:

- [Singla et al. (2005), experimental MASCOTTE G2](https://doi.org/10.1016/j.proci.2004.08.063)
- [Cavalieri et al. (2025), modern G2 real-fluid and geometry context](https://doi.org/10.1016/j.ijheatmasstransfer.2025.127284)
- [Sharma, De, and Kumar (2023), diffusion-flamelet FGM configuration](https://doi.org/10.1615/InterJEnerCleanEnv.2022045212)

See `reference/comparison-contract.json` for the exact evidence boundary and
controlled-comparison metadata.
