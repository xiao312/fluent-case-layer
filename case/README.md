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
