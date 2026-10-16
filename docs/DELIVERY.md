# Verified Python delivery - v5

The submission contains the complete retained exact-filter cohort with explicitly partial enrichment: **4,983 locations in 3,129 applications; 4,927 assigned FHWA classes and 56 unresolved locations**. This is a 2026-to-date public-source capture, not a complete annual census or a field-surveyed roadway assignment. The assessment permits documented partial results. Nothing has been uploaded to its submission destination.

## Current packages

Use the verified v5 Python archive committed at `submission/Yuhan_Wu_Python.zip`. Its checksum and validation record are in the same directory. Earlier v3/v4 archives are historical and superseded for delivery.

- Python ZIP: `deliverables/python_v5_readme_final/Yuhan_Wu_Python.zip`.
- Parent archive: `deliverables/python_v5_readme_final/Yuhan_Wu_CS12_DataScientist_Tests.zip`.
- Checksums and measured verification: `SHA256SUMS.txt` and `verification.json` in that directory.
- Main CSV: `artifacts/runs/final_mar_v5/permits_enriched.csv`.
- New assignments and remaining cases: `resolved_changes.csv`, `remaining_exceptions.csv`, and `change_review.json` in the same run directory (also included inside the ZIP).

The parent archive contains `Yuhan_Wu/Yuhan_Wu_Python.zip`. The ordinary source tree retains the small pilot; the committed `submission/Yuhan_Wu_Python.zip` supplies the full frozen data and outputs after a normal clone. Large uncompressed captures and generated local ZIPs remain ignored. The root README shows how to extract and reproduce the full package. Parent-archive generation is documented separately in USAGE.

## Measured result

| Measure | Value |
| --- | --- |
| Selected locations / applications | 4,983 / 3,129 |
| Assigned FHWA class / unresolved | 4,927 / 56 |
| Class-complete / incomplete applications | 3,073 / 56 |
| Baseline nearest-road / exact MAR / intersection class consensus | 4,828 / 89 / 10 |
| DC Water / PEPCO / Washington Gas locations | 1,911 / 1,403 / 1,669 |
| Construction Staging Area / Mobile Crane Work Zone | 4,983 / 0 |
| Original source fields retained | 113 |
| Date/type cohort / excluded utility controls | 7,279 / 2,296 |

All source fields and geometry agree with the original v4 output. Every one of the original 4,828 accepted locations retains its road key/name/type/distance and FHWA class. The 99 new outcomes are restricted to prior exceptions. The 10 intersection outcomes assign a shared class with all supporting keys; unique-road fields are blank. Application completeness means class coverage, not a unique roadway assertion. See [output fields](OUTPUT_FIELDS.md).

## Source and supplementary evidence

Permit retrieval was 2026-10-15 01:17:01-01:17:08 UTC; the original snapshot finalized at 02:04:10 UTC. Its manifest SHA-256 is `bc506840f302fb0cd313d3208880078b217c695d0fa28f59f5714bb8848e8c9f`.

The new snapshot `artifacts/snapshots/full_20261014_mar_v5` retains those original data hashes and a copy of that manifest. Later public MAR/road responses were retrieved around 2026-10-16 02:43:14-02:43:15 UTC and are retained in the hashed `mar_evidence.json` (106 address records, 103 roadway records). They are supplementary observations, not a claim that all services formed one atomic snapshot. No source geometry was moved and the LRS service was not called during this supplement.

## Remaining 56 cases

| Existing exception reason | Rows |
| --- | --- |
| Different-road near tie | 24 |
| No eligible road within 50 m | 14 |
| Numbered street disagreement | 13 |
| Multiple exact unit blocks | 4 |
| Unit-block disagreement | 1 |

The remaining cases include 21 intersection descriptions (different-class or special forms), 18 MAR references outside the frozen 50 m candidate set, 13 block-range cases, 3 exit/ramp descriptions and 1 MAR address without a usable key. These evidence groups are disjoint. The tool does not expand the radius, infer a ramp's identity, take the highest class from conflicting roads or force an address reference into a confirmed work-road assignment. The utility-looking excluded-identity heuristic returned zero cases, which does not prove exhaustive contractor/alias coverage.

## Verification

The actual v5 Python ZIP passed CRC, path and file-membership checks. Extracting it into a new Windows path containing spaces and installing its own requirements in a new Python 3.11 environment produced **59 passing tests**. Delivered-output verification, full regeneration and regenerated-output verification all passed. The regenerated CSV is byte-identical to the delivered result.

CSV SHA-256: `de7da3cb23d3b534f99fd589cdbfaa6cb513d16dd59e5770677676c753a6f772`.

Python ZIP SHA-256: `322e68aca2db83113e2c10569a616a6d9b4fe9031c51359f4d84fdc2031e7ba9`.

Parent ZIP SHA-256: `7badda205815b521a0aa6a6745918597960adfa2f4ab13e8803808d9dbce8486`.

The code, evidence and archive are ready to deliver as a documented partial enrichment. Review the README, REPORT and 56 exception rows before sending the named parent archive to the supplied assessment destination. Further case resolutions require a new policy/result and a newly verified package.

## Local absolute file paths

The following locations apply to this Windows workspace; recipient machines should use the absolute-path listing commands in the extracted package README.

- Python package: `E:/ddot_1015/cs12-data-scientist-assessment/submission/Yuhan_Wu_Python.zip`.
- Local parent package: `E:/ddot_1015/cs12-data-scientist-assessment/deliverables/python_v5_readme_final/Yuhan_Wu_CS12_DataScientist_Tests.zip`.
- Main CSV: `E:/ddot_1015/cs12-data-scientist-assessment/artifacts/runs/final_mar_v5/permits_enriched.csv`.
- Outstanding cases: `E:/ddot_1015/cs12-data-scientist-assessment/artifacts/runs/final_mar_v5/remaining_exceptions.csv`.

The ZIP README documents the scripts, final CSV, report, exceptions, frozen inputs, supplementary evidence and their complete paths beneath the extracted folder. Its PowerShell listing resolves the actual absolute paths for each recipient.

## Direct results

The repository also provides a direct [final CSV](../results/permits_enriched.csv), [exceptions](../results/EXCEPTIONS.csv) and [report](../results/REPORT.json). The direct CSV has the same SHA-256 as the packaged output. Its local full path is `E:/ddot_1015/cs12-data-scientist-assessment/results/permits_enriched.csv`.
