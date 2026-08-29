# Canonical illustrative case

This directory is a complete, schema-valid example of the split case format.
It is intentionally illustrative: the locked mesh URI and checksum demonstrate
the asset contract but do not identify a runnable mesh. Copy this directory,
replace the asset record with a real immutable object, then specialize the
physical intent and stage gates.

Case documents contain no personal or machine-local paths. Platform profiles
refer to environment variables that the launcher resolves at runtime. Loading
the case validates structure and cross-file references without importing or
launching Fluent.

`system/objectives.yaml` records engineer intent as non-enforcing guidance;
typed aspects may point at monitors or reference data, but they are never
promoted into gates implicitly. Any gates in `system/monitors.yaml` are
case-local judgments and remain optional.

`system/state.yaml` declares the Fluent state this layer owns and the state it
will record. In `checkpoint_overlay` mode, all undeclared state is implicitly
inherited from the exact hash-locked case/data baseline; no exhaustive
allowlist is required.
