# Field evidence and extraction

Fluent field evidence is not trustworthy merely because an API call returned a
NumPy-shaped object. A case may sample scalar health indicators live while
requiring a completed Fluent checkpoint for multidimensional fields. The plan,
adapter result, and artifact manifest must preserve that distinction.

The official PyFluent documentation distinguishes the surface-oriented
[`field_data` API](https://fluent.docs.pyansys.com/version/stable/user_guide/fields/field_vs_svars_data.html)
from the zone-oriented, read/write
[`solution_variable_data` API](https://fluent.docs.pyansys.com/version/stable/api/services/solution_variables.html).
Neither interface removes the need to validate returned array semantics against
the active Fluent state.

## Acquisition choices

| Need | Preferred source | Required evidence | Typical use |
| --- | --- | --- | --- |
| residual/report history | Fluent monitor or report-definition API | monitor/report identity, unit, sample index or iteration, raw value | live numerical inspection |
| scalar cell-zone state | `solution_variable_data` | Fluent/PyFluent versions, domain, zone, SVAR, dimension, cell count, finite/range checks | temperature, density, pressure, velocity |
| surface field | `field_data` or a report definition | surface IDs/names, field name, operation, unit, element count | inlet/outlet and wall evidence |
| vector or multi-component cell state | live SVAR only after a parity qualification; otherwise completed `.dat.h5` checkpoint | checkpoint hash, dataset path, shape, dtype, component order, cell count, invariants | species vectors and other coupled state |
| derived observable | verified source arrays plus a versioned equation | source artifact hashes, equation/constants/units, normalization, output hash | OH-star proxy, mixture fraction, custom QoI |

`sample` and `checkpoint/export` are therefore different stages. An agent may
use cheap scalar samples to decide whether to continue, interrupt, or retain a
checkpoint. It must not infer that an unqualified vector stream is safe because
scalar streams from the same service are valid.

## Variable identity and cell ordering

Treat solution-variable identifiers as version-qualified Fluent API tokens,
not human-readable abbreviations. The adapter must retain the requested token,
the physical quantity and unit it maps to, and readback evidence for the active
Fluent version. Similar-looking tokens are not interchangeable: in one Fluent
2026 R1 case, `SV_DENSITY` was physical density while `SV_D` held a different
internal quantity with values up to `3.14e8`. A plausible shape does not prove
the semantic mapping.

Likewise, a checkpoint cell dataset and a live PyFluent cell-zone buffer may
contain the same cells in different orders. Before pairing a checkpoint field
with live centroids, require one of these alignment proofs:

1. stable cell identifiers exposed by both sources and an explicit ID join; or
2. a one-to-one permutation built from an exact, unique scalar anchor, then
   independently reproduced by multiple additional checkpoint/live scalar
   fields.

Record the alignment method, zone/domain, cell count, anchor identity,
permutation digest, comparison tolerances, and cross-field parity results.
Reject ambiguous anchors, duplicate mappings, incomplete coverage, or failed
cross-field parity. Bounds, component count, and row-sum invariants are
necessary but do not establish spatial alignment.

## Multi-component qualification

Before a vector-valued solution variable is used for a numerical or scientific
judgment, verify all of the following:

1. The observed component dimension matches the authored component order.
2. The row count matches the Fluent-observed zone cell count.
3. Every value is finite and satisfies field-specific bounds.
4. Field invariants hold; for species mass fractions, each row is within the
   allowed tolerance of `[0, 1]` and sums to one.
5. A representative live extraction agrees with the same state written by
   Fluent to a checkpoint, within a declared tolerance.
6. Checkpoint rows are explicitly aligned to the coordinates or topology used
   for spatial interpretation, with ID-join or permutation evidence.
7. The parity evidence is qualified by Fluent version, PyFluent version, domain,
   zone type, field, dimension, and precision.

Until step 5 succeeds, the checkpoint is authoritative for postprocessing and
the live vector path remains unsupported for that qualified state. Do not clip,
renormalize, reinterpret bytes, transpose by guesswork, or reconstruct a missing
component merely to make a corrupt payload look physical.

## Artifact manifest

A checkpoint-derived field record should include at least:

```yaml
source:
  kind: fluent_checkpoint_hdf5
  checkpoint_sha256: <64 lowercase hex characters>
  dataset: /results/1/phase-1/cells/SV_Y/1
  dtype: float64
  shape: [123600, 9]
  domain: mixture
  zone: fluid
components: [CH4, O2, CO, H2, H2O, O, H, OH, CO2]
validation:
  finite: true
  bounds: [0.0, 1.0]
  maximum_row_sum_error: 2.3e-15
  row_alignment:
    method: exact_unique_scalar_anchor_with_cross_field_parity
    anchor: SV_T
    permutation_sha256: <64 lowercase hex characters>
    parity_fields: [SV_P, SV_U, SV_V]
derived_outputs:
  - role: field_data
    path: reacting-preliminary-fields.npz
    sha256: <64 lowercase hex characters>
```

The dataset path is observed evidence, not a universal constant. Discover it
inside the verified checkpoint and fail if discovery is ambiguous. Large field
payloads remain outside Git; Git retains the case intent, extraction policy,
compact manifest, and engineering judgment.

## Version-qualified incident

In an executed Fluent 2026 R1 / `ansys-fluent-core 0.40.2` finite-rate species
case, scalar SVARs were valid while the nine-component `SV_Y` byte stream
decoded to non-finite and extreme values. Fluent's completed `.dat.h5` held a
normalized cell-by-species matrix for the same state. The case runner therefore
used live scalar health sampling and checkpoint-backed species/OH export, with
independent bounds and row-sum verification. A subsequent spatial audit found
that the checkpoint matrix used global cell ordering while live PyFluent
centroids used partition-local ordering. The retained checkpoint remained
valid, but the first derived contour artifact was superseded. An exact
temperature-based permutation, independently confirmed against pressure and
both velocity components, produced the corrected spatial evidence.

This incident is not evidence that every PyFluent vector read is broken. It is
evidence that support must be qualified by field, dimension, solver state, and
version. A later PyFluent release may restore the live path after a recorded
checkpoint-parity test; static case YAML need not change.

## Human and agent interpretation

- An extraction or parity failure is an orchestration/evidence failure, not a
  statement about the simulated physics.
- A physically bounded field is necessary evidence, not convergence or
  agreement with experiment.
- Relative colormaps and derived fields must retain their normalization and
  source-array provenance.
- Human review may change which fields and invariants matter as the
  investigation deepens; preserve earlier attempts instead of rewriting them.
