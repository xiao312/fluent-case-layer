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

Answers will be recorded here as short ADR-style entries with date, context,
decision, consequences, and follow-up implementation work.
