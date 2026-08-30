# MASCOTTE G2 Wuzhen setup/readback attempts

Status on 2026-08-31: **blocked before complete settings readback**. Two bounded
Fluent 2026 R1 CPU attempts exercised model setup only. Neither attempt
calculated a flamelet, calculated a PDF table, initialized a flow solution, or
advanced an iteration. Neither produced `SUCCESS`.

This note records runtime integration evidence. It does not establish a usable
FGM table, a flow solution, convergence, or agreement with experiment.

## Attempt record

| Job | Commit | Snapshot SHA-256 | Terminal result | Runtime boundary |
| --- | --- | --- | --- | --- |
| `43266182` | `d409049f4827dc942e4b66b518a5f10a60d8496c` | `470d240a0c7ab6f88768f75865fbb6b99084431646d60d2131c018a32174b665` | `FAILED`, exit `1:0`, 60 s | `species_boundary.list()` returned `None`; the caller tried to iterate it |
| `43266815` | `12f08439e0d2e749e910194b0abb7a406510e766` | `dab838c09834a092870f9ae6b4aeb0bf889790815267b3069b5bfded5b0ceb98` | `FAILED`, exit `1:0`, 52 s | species discovery passed; PDF selection stopped because `allowed_values()` returned `[]` |

Both jobs used account `ac8azwcnf1`, partition `wzacnormal03`, node
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

## Remaining blocker: PDF allowed-value evidence

The retry stopped at the exact PDF request. The active Fluent node returned an
empty list from `probability_density_function.allowed_values()`. Because the
probe requires the requested `beta` option to appear in live runtime metadata
before calling its setter, it failed closed. It did not substitute the typed
schema enum, infer the option from another release, or weaken the readback
requirement.

Complete group state was therefore not serialized, and the independent
verifier did not run. A future revision needs a documented, read-backable
Fluent 2026 R1 route for the active PDF option before another execution can be
considered. Resolving this metadata route would only make the setup/readback
probe eligible to complete; it would not authorize flamelet or PDF-table
calculation.

Fluent also emitted an oxidizer normalization warning while individual stream
fractions were being applied. Since the probe stopped before complete boundary
group readback, this note makes no claim that the final stream state was valid.

## Safety and retention boundary

The preflight provenance for both attempts records all four permissions as
false: flamelet calculation, PDF calculation, initialization, and iterations.
The retained remote transcripts were scanned with
`calc[_ -]?fla|calc[_ -]?pdf|initialize|iterate`; neither contained a match.
`SUCCESS` and `verification.json` were absent from both terminal run
directories.

Only small JSON records created by this repository are copied here:

- [job 43266182 provenance](job-43266182/execution-provenance.json) and
  [structured failure](job-43266182/setup-readback-failure.json);
- [job 43266815 provenance](job-43266815/execution-provenance.json) and
  [structured failure](job-43266815/setup-readback-failure.json).

No mesh, chemistry, reference-data, Fluent case/data, transcript, Slurm log, or
field artifact is stored in Git. Hashes of the uncopied operational evidence
are retained in the manifest so an authorized engineer can audit the original
run directories without treating those files as repository inputs.
