# MASCOTTE G2 Wuzhen setup/readback attempts

Status on 2026-08-31: **blocked before complete settings readback**. Three
bounded Fluent 2026 R1 CPU attempts exercised model setup only. None calculated
a flamelet, calculated a PDF table, initialized a flow solution, or advanced an
iteration. None produced `SUCCESS`.

This note records runtime integration evidence. It does not establish a usable
FGM table, a flow solution, convergence, or agreement with experiment.

## Attempt record

| Job | Commit | Snapshot SHA-256 | Terminal result | Runtime boundary |
| --- | --- | --- | --- | --- |
| `43266182` | `d409049f4827dc942e4b66b518a5f10a60d8496c` | `470d240a0c7ab6f88768f75865fbb6b99084431646d60d2131c018a32174b665` | `FAILED`, exit `1:0`, 60 s | `species_boundary.list()` returned `None`; the caller tried to iterate it |
| `43266815` | `12f08439e0d2e749e910194b0abb7a406510e766` | `dab838c09834a092870f9ae6b4aeb0bf889790815267b3069b5bfded5b0ceb98` | `FAILED`, exit `1:0`, 52 s | species discovery passed; PDF selection stopped because `allowed_values()` returned `[]` |
| `43271670` | `c7a71e213e316fc12160c2e2df1b51d596cf53d1` | `81a70de04e744a66afe49bc725d5912cc116f8e93fbd5187423a2b842d276d05` | `FAILED`, exit `1:0`, 85 s | metadata channels agreed that `beta` exists statically, but the PDF leaf was inactive and unreadable; no setter ran |

All three jobs used account `ac8azwcnf1`, partition `wzacnormal03`, node
`b10r4n33`, one Fluent rank, and four allocated CPUs. Exact run paths,
scheduler timestamps, artifact hashes, and guard results are in
[`evidence-manifest.json`](evidence-manifest.json).

## Fixed: species-boundary discovery

The first attempt exposed an API-semantics bug in the probe, not an unknown
species set. In PyFluent 0.40.2 for Fluent v261, `NamedObject.list()` delegates
to a display command and returns no programmatic value. The supported
`NamedObject.get_object_names()` path calls
`flproxy.get_object_names(object_path)` and returns the names as a list.

Commit `12f08439e0d2e749e910194b0abb7a406510e766` changed discovery to that
programmatic API and made malformed, empty, non-string, and duplicate results
fatal. The second attempt imported JL9 and progressed beyond the former
species-enumeration line. That runtime progression is the evidence that the
first gap was fixed; it is not evidence that all stream settings were captured
successfully.

## Resolved ambiguity: empty helper metadata

The second attempt's empty `allowed_values()` result did not distinguish an
unsupported enum from a PyFluent metadata omission. Commit
`c7a71e213e316fc12160c2e2df1b51d596cf53d1` added separate capture envelopes
for helper metadata, raw `active?`/`read-only?`/`allowed-values` attributes,
leaf and parent state, the generated v261 class, and the runtime static-info
subtree. Exceptions are retained as exceptions instead of being collapsed into
empty lists. A setter is allowed only after all active, writable, version,
static-enum, and runtime-static-info preconditions pass; an already-selected
leaf and parent `beta` state may instead pass as a zero-setter no-op.

Job `43271670` showed that `beta` is present in both the generated v261 enum and
the server static-info enum. It also established the actual PyFluent 0.40.2
generated-module alias `settings_261`, which the post-run adapter accepts only
alongside the exact class, version, exposure level, setting path, and enum.
Thus the empty helper result is not evidence that Fluent 2026 R1 lacks the
`beta` selection.

## Remaining blocker: inactive PDF setting

The same structured probe returned raw `active? = false`, omitted writable and
dynamic enum attributes, returned an empty parent group, and raised
`api-get-var: the object is not active` for the exact PDF leaf. The generated
and runtime-static schemas do not override that live inactive state. The
adapter therefore recorded `setter_authorized = false` and stopped with no
setter call.

Complete group state was therefore not serialized, and the independent
verifier did not run. A future revision needs a documented Fluent 2026 R1 model
state in which this PDF leaf is active and both leaf and parent state are
readable. Static enum presence alone is insufficient. Resolving activation
would only make a setup/readback probe eligible; it would not authorize
flamelet or PDF-table calculation.

Fluent also emitted an oxidizer normalization warning while individual stream
fractions were being applied. Since the probe stopped before complete boundary
group readback, this note makes no claim that the final stream state was valid.

## Safety and retention boundary

The preflight provenance for all three attempts records all four permissions as
false: flamelet calculation, PDF calculation, initialization, and iterations.
The retained remote transcripts were scanned with
`calc[_ -]?fla|calc[_ -]?pdf|initialize|iterate`; none contained a match.
`SUCCESS` and `verification.json` were absent from all three terminal run
directories.

Only small JSON records created by this repository are copied here:

- [job 43266182 provenance](job-43266182/execution-provenance.json) and
  [structured failure](job-43266182/setup-readback-failure.json);
- [job 43266815 provenance](job-43266815/execution-provenance.json) and
  [structured failure](job-43266815/setup-readback-failure.json);
- [job 43271670 provenance](job-43271670/execution-provenance.json) and
  [structured metadata failure](job-43271670/setup-readback-failure.json).

No mesh, chemistry, reference-data, Fluent case/data, transcript, Slurm log, or
field artifact is stored in Git. Hashes of the uncopied operational evidence
are retained in the manifest so an authorized engineer can audit the original
run directories without treating those files as repository inputs.
