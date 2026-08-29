# Transient 1D H2/air

This is an illustrative migration of the executed `transient-1d-h2-air` DFODE
recipe.  It exercises the fresh-mesh path: load a generated 1000 x 1 planar
mesh, reconcile finite-rate chemistry and boundaries, patch a burned half,
advance 5,000 fixed time steps, sample evidence, and write a checkpoint.

The source workflow ran on SCNET, but this split-config translation has not.
Set `FCL_H2_AIR_ASSET_ROOT` to a directory containing the relative paths in
`case/assets.lock.yaml`; the lock hashes are from the source recipe's prepared
assets.  Platform environment variables are resolved by the launcher, not by
these case files.

Known migration gap: the source recipe derives the flame speed and equilibrium
state in a Cantera preprocessing step and compiles a chemistry UDF.  This
example locks the resulting mesh, CHEMKIN files, and UDF source and records the
verified equilibrium patch, but the current stage schema has no typed
preprocess or UDF-build stage.  See `docs/example-migration-notes.md`.
