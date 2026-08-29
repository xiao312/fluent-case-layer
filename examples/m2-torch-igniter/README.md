# M2 torch igniter continuation

This illustrative case migrates the internal `fluent-torch-igniter-m2`
checkpoint workflow. It reads the hash-locked iteration-500 case/data pair,
creates two cylindrical registers, patches `premixc` in the verified order,
writes a restart checkpoint, and runs four 500-iteration evidence windows.
`system/state.yaml` is a `checkpoint_overlay`: only those four register/patch
mutations are declared as owned. The broader 2 MPa setup, methane/oxygen
boundaries, models, materials, chemistry, fields, and numerical methods are
inherited and observed for compatibility, not claimed as reconstructed state.

The current driver has no path-scoped settings reconciler, so the case does not
pretend to apply narrow pressure, boundary, or method edits through a broad
whole-document stage. A real run must hold if the observed checkpoint differs
from the expected split documents until a narrow adapter or an engineer-
approved mutation is available.

The legacy four-rank workflow completed to iteration 2,500.  The split-config
translation has not been executed.  The source continuation was operational,
not scientifically accepted: continuity remained near order one, cells left
the PDF enthalpy range, and the original postprocessing was pending.  The
objective therefore asks an open wall-risk question and assumes no ranking.
It is non-enforcing and separate from the case-local artifact, reacting-state,
and window-stability checks; the historical run is not claimed to pass them.

Set `FCL_M2_ASSET_ROOT` to a directory with the locked relative paths in
`case/assets.lock.yaml`.  The two registers reproduced 89,725 and 47,542
selected cells in the source smoke run; a driver must record resolved cell
counts and fail or require review on drift.

Agent investigations may retain and compare modified candidates, including
failed and rejected attempts, and may promote a candidate with an attributable
reason and recoverable predecessor. Geometry and mesh changes are within the
eventual authority, but this example intentionally inherits the baseline mesh
and the current adapter must expose unsupported changes as gaps. A rich human-
collaboration UI is deferred; consequential physical, geometry, or resource
choices still require an engineer interruption.
