# Effusion cooling with DRM19 FGM and DPM

This illustrative case captures the executed Fluent 2026 R1 effusion-cooling
tutorial as a multi-stage intent: PMDB meshing, DRM19 flamelet/PDF generation,
continuous-phase and DPM reconciliation, 300 cold-flow iterations, a
`premixc=1` combustor patch, 400 reacting iterations, and evidence/checkpoints.

The legacy four-rank workflow passed 42 setup assertions and produced all
requested images.  Its fixed-iteration field reached 2458.78 K on the
mid-plane, while final continuity and energy residuals remained above their
configured criteria.  That is executed tutorial evidence, not scientific
validation of this translation.

Set `FCL_EFFUSION_ASSET_ROOT` to the extracted source directory represented by
`case/assets.lock.yaml`.  No generated mesh or licensed asset is committed.

Two current schema/driver gaps are deliberate and visible:

- `declare-meshing-intent` records the real PMDB, face sizing, periodic pair,
  boundary-layer, and volume-mesh parameters, but the stage model cannot yet
  launch a Fluent Meshing workflow, switch that session to Solver, or emit a
  typed mesh artifact.  It is a declaration stage, not a claim of execution.
- DPM interaction cadence is typed in `physics.yaml`; detailed cone injection,
  turbulent dispersion, and perforated-wall values are carried as typed stage
  inputs until dedicated injection and perforated-wall schemas exist.

See `docs/example-migration-notes.md` for the promotion path.
