# Transient 1D H2/air

This is an illustrative migration of the executed `transient-1d-h2-air` DFODE
recipe.  It exercises the fresh-mesh path: load a generated 1000 x 1 planar
mesh, reconcile finite-rate chemistry and boundaries, patch a burned half,
advance 5,000 fixed time steps, sample evidence, and write a checkpoint.
`system/state.yaml` therefore uses `full_definition`: the layer owns the
fresh-case setup listed there, while undeclared values retain Fluent defaults.

The versioned engineering objective is non-enforcing. It asks for numerical
health, persistent flame propagation, and a thermal comparison with the locked
Cantera FreeFlame simulation profile. That model-to-model reference is not an
experiment and is not silently converted into an acceptance gate.

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

Agent investigations may retain and compare modified candidates, including
failed and rejected attempts, and may promote a candidate with an attributable
reason and recoverable predecessor. Geometry and mesh controls are within the
eventual mutation authority, but this initial adapter can only consume the
locked mesh and reports regeneration as a mapping gap. A rich human-
collaboration UI is deferred; consequential physical, geometry, or resource
choices still require an engineer interruption.
