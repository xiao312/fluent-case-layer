# M2 torch igniter continuation

This illustrative case migrates the internal `fluent-torch-igniter-m2`
checkpoint workflow.  It reads the iteration-500 case/data pair, reconciles the
owner-approved 2 MPa methane/oxygen state, creates two cylindrical registers,
patches `premixc` in the verified order, writes a restart checkpoint, and runs
four 500-iteration evidence windows.

The legacy four-rank workflow completed to iteration 2,500.  The split-config
translation has not been executed.  The source continuation was operational,
not scientifically accepted: continuity remained near order one, cells left
the PDF enthalpy range, and the original postprocessing was pending.  The
scientific wall-risk gates here therefore remain real requirements, not claims
that the historical run passed them.

Set `FCL_M2_ASSET_ROOT` to a directory with the locked relative paths in
`case/assets.lock.yaml`.  The two registers reproduced 89,725 and 47,542
selected cells in the source smoke run; a driver must record resolved cell
counts and fail or require review on drift.
