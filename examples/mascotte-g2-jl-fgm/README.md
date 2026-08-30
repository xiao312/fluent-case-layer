# MASCOTTE G2 reduced-JL diffusion-FGM probe

This case keeps two claims separate:

1. A historical reproduction is **blocked**. The audit found no provenance-locked
   G2 Fluent flamelet (`.fla`) or PDF table, and the primary FGM source does not
   report enough Fluent controls to regenerate its table uniquely.
2. An **engineer-selected exploratory setup/readback probe** is defined for
   Fluent 2026 R1. It imports the locked reduced-JL CHEMKIN files, selects the
   partially-premixed diffusion-FGM model, pure G2 streams, finite-rate TCI,
   transported progress-variable variance, beta PDF, automatic Fluent progress
   variable, and exact SRK density. It serializes every active settings group and
   allowed enum value without calculating flamelets, calculating a PDF table, or
   advancing the flow solution.

The probe deliberately leaves flamelet integration, scalar-dissipation,
adaptation, enthalpy, and PDF-table grid controls at their active Fluent 2026 R1
runtime values. Those complete groups are read back as evidence. A later revision
must review and freeze every value before any table-generation code may exist.
The paper's statement of 64-point automatic resolution is retained in the
comparison contract, but is not mapped onto a guessed Fluent node.

Set `MASCOTTE_G2_ASSET_ROOT` to the directory containing `mesh/` and `jl9/` with
the bytes locked in `case/assets.lock.yaml`. Set `MASCOTTE_G2_REFERENCE_ROOT` to
the directory containing the locked digitized OH-star NPZ. The reusable case
contains no machine-specific SCNET path.

`automation/setup_readback_smoke.py` is only a future execution scaffold. It
requires an explicit setup-only confirmation, launches no scheduler job, and
contains no table-calculation or iteration path. Its JSON result is a discovery
artifact, not a table, converged solution, or validation result.

Primary context:

- [Singla et al. (2005), experimental MASCOTTE G2](https://doi.org/10.1016/j.proci.2004.08.063)
- [Cavalieri et al. (2025), modern G2 real-fluid and geometry context](https://doi.org/10.1016/j.ijheatmasstransfer.2025.127284)
- [Sharma, De, and Kumar (2023), diffusion-flamelet FGM configuration](https://doi.org/10.1615/InterJEnerCleanEnv.2022045212)

See `reference/comparison-contract.json` for the exact evidence boundary and
controlled-comparison metadata.
