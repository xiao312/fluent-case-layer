# Design interview and decision log

This document captures the questions that determine the product boundary. It
is intentionally separate from implementation notes: answers become explicit
architecture decisions, schema changes, or deferred work.

## Round 1 — product contract

1. Is the product primarily a Fluent-specific case format, or a solver-neutral
   CFD campaign layer whose first mature adapter is Fluent?
2. Should authored files express desired end state, an exact ordered procedure,
   or desired state plus explicit stage actions for order-sensitive operations?
3. Which users are primary in the first six months: CFD engineers authoring
   cases, agents repairing cases, or platform engineers operating campaigns?
4. What must remain editable without Python: all common models and boundary
   conditions, only operating conditions, or the entire stage graph?
5. Which first real case defines v0 success, and what exact evidence would make
   you trust a replay by someone who did not create it?
6. Is compatibility with Fluent releases other than 2026 R1 a v0 constraint or
   only an adapter-design constraint?

## Round 2 — state, mutation, and escape hatches

1. May a case inherit hidden state from a `.cas.h5` checkpoint, or must every
   relied-upon setting be declared/audited after load?
2. When desired and observed state differ, should `apply` repair automatically,
   stop for approval, or follow per-field policy?
3. What kinds of TUI/Python escape hatches are acceptable? Must they be typed
   plugins, versioned scripts, or may a case include audited raw commands?
4. Which actions need transaction-like rollback? Is writing a recovery
   checkpoint before every destructive model transition sufficient?
5. What makes a checkpoint promotable to roles such as `setup`, `warm-start`,
   `qualified`, or `production`?

## Round 3 — campaign and agent behavior

1. Should one failing case stop a campaign, isolate only its dependent stages,
   or continue all independent work by default?
2. Which resource limits are hard policy: active Slurm jobs, total core-hours,
   wall-clock deadline, licenses, storage, or monetary model budget?
3. What repairs may the agent make autonomously? Which changes require human
   approval because they alter physics rather than numerics/operations?
4. Should every repair be an overlay/patch that can be reviewed and promoted,
   or may the agent edit the canonical case directly on a development branch?
5. Do failed runs become first-class benchmark fixtures with expected diagnosis
   and repair, or only retained audit evidence?

## Round 4 — validation and publication

1. Which status axes are mandatory for every case: asset readiness, execution,
   numerical health, scientific validation, and publication readiness?
2. Are scientific gates authored inside the case, supplied by an external
   verifier, or both with explicit trust levels?
3. Where should large immutable assets live, and what URI schemes must v0
   support on laptops and SCNET?
4. Which run evidence belongs in Git, Git LFS, object storage, and ephemeral
   scratch?
5. What is the minimum reproducibility promise: same configuration and valid
   trend, matching engineering QoIs within tolerance, or bitwise/field-level
   equivalence?

## Decisions

### 2026-08-29 — Round 1 product decisions

| ID | Decision | Architectural consequence |
| --- | --- | --- |
| D-001 | The product supports **ANSYS Fluent/PyFluent only**. OpenFOAM is an inspiration and historical workflow reference, not a target adapter. | Fluent concepts may be modeled directly. The project does not promise solver-neutral schemas, shared physics types, or an OpenFOAM execution path. |
| D-002 | The primary users are the **internal CFD simulation team**. | Optimize for expert-readable intent, inspectable plans, interactive diagnosis, and deep human review rather than a simplified public authoring experience. |
| D-003 | The current cases belong to **one semantic complexity tier**. | Do not split the case model into simple and advanced products. Runtime cost, data size, and failure risk may still control execution order and resource policy. |
| D-004 | During an investigation, the agent may change **any in-scope simulation setting** if it can improve the result. | Physics, models, chemistry, boundaries, initialization, numerics, and operating procedure are not separated into fixed autonomous-versus-approval classes. Every attempted mutation and its evidence must remain inspectable. The boundary around geometry/mesh changes and promotion into the canonical case remains open. |
| D-005 | A checkpoint-backed case must be **universally usable as a partial mutation layer**; exhaustive declaration, a fixed allowlist, and complete state reconstruction are too strict. | Lock the baseline asset identity, declare only the state the layer intends to own or change, and distinguish inherited, observed, and declared state. Uninspected Fluent state remains explicit rather than being treated as absent or falsely verified. |
| D-006 | There is **no universal acceptance or checkpoint-promotion contract**. Goals, diagnostics, and judgments are case-local, evolve during the simulation effort, and are deepened by human engineers. | Gates are optional evidence, not a global definition of success. Execution facts, current numerical/scientific judgments, and human review notes remain separate; missing judgments are `not_evaluated`, not failures or passes. |

These decisions supersede any roadmap language that implies an OpenFOAM
adapter, a solver-neutral product, exhaustive ownership of loaded Fluent state,
or mandatory scientific gates.

### Round 2 focus after these decisions

The next interview should resolve only the remaining operational choices:

1. how a run states its current, revisable meaning of “better”;
2. whether an agent edits the canonical case or always emits a candidate;
3. how often the agent should interrupt an engineer during expensive work;
4. whether rejected attempts are retained as first-class learning fixtures;
5. whether broad mutation authority includes geometry and mesh topology; and
6. how inherited, observed, and declared checkpoint state should appear in the
   UI and evidence record.
