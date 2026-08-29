# Runtime option discovery

PyFluent settings are stateful. Official settings objects expose metadata such
as `is_active`, `is_read_only`, `default_value`, `allowed_values`, `min`, and
`max`; the available values can change after loading a mesh or enabling a model.
See the official [solver settings documentation](https://fluent.docs.pyansys.com/version/dev/user_guide/solver_settings/solver_settings_contents.html)
and [settings service API](https://fluent.docs.pyansys.com/version/stable/api/services/settings.html).

The case-layer schema therefore defines a stable authoring vocabulary, not a
claim that every Fluent state exposes every option.

## Static versus runtime facts

| Fact | Durable home |
| --- | --- |
| Case key, type, enum, default, and unit contract | Pydantic schema and generated catalog |
| Intended Fluent concept and PyFluent path | Reviewed coupling registry |
| Active/read-only state and allowed values | Runtime snapshot for one Fluent state |
| Mapping implementation and option support | Adapter code, tests, and coverage status |
| Engineering choice and rationale | Candidate attempt/evidence record |

## Snapshot envelope

Runtime discovery should be recorded without changing static documentation:

```json
{
  "snapshot_version": "1.0",
  "fluent_version": "2026 R1",
  "pyfluent_version": "0.x",
  "case_state_digest": "sha256-of-observed-prerequisite-state",
  "captured_at": "2026-08-29T08:00:00Z",
  "entries": {
    "constant/physics.yaml#/solver/time": {
      "pyfluent_path": "setup.general.solver.time",
      "is_active": true,
      "is_read_only": false,
      "allowed_values": ["steady", "unsteady-1st-order", "unsteady-2nd-order"],
      "default_value": "steady"
    }
  }
}
```

This is an observation, not a portable case definition. It must include Fluent
version and a digest or description of prerequisite state because allowed values
without activation context are misleading.

## Safe probe order

1. Launch or attach to the exact target Fluent release.
2. Load and hash-verify the intended mesh/checkpoint.
3. Enable prerequisite models in the same order as the candidate plan.
4. Resolve the reviewed PyFluent path.
5. Capture active/read-only/default/allowed/min/max attributes without mutating it.
6. Store the observation with version and state provenance.
7. Compare it with static choices and adapter option support.

Do not automatically expand the case schema from one runtime observation. A new
portable option requires engineering review across relevant solver states and a
version-qualified mapping. Conversely, a runtime allowed value may use Fluent's
internal spelling while the authored schema deliberately exposes a cleaner,
stable name; the adapter owns that translation.

## Current boundary

The catalog records which fields need runtime metadata, but this release does
not launch Fluent merely to build documentation. Automated snapshot capture will
be added alongside typed reconcilers, where activation prerequisites and named
object discovery can be tested safely. Until then, agents must label manually
captured metadata as case-state evidence and must not promote a candidate path
to `implemented` from documentation alone.
