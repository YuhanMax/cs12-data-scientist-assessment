# Running and packaging

Use Python 3.10 or newer. The examples select Python 3.11 explicitly because another installed `python` may be older. Create `.venv` and install the root `requirements.txt` as shown in the [README](../README.md). Activation, ArcGIS Pro and MAR credentials are not required.

## Obtain the project and full package

Clone `https://github.com/YuhanMax/cs12-data-scientist-assessment.git` using an authorized GitHub account and follow the [root README](../README.md). A normal clone includes the self-contained full-data archive at `submission/Yuhan_Wu_Python.zip`, plus its checksum. The source-level `artifacts/` tree includes only the small pilot; full-data reproduction uses the extracted submission package. The README provides exact extraction and verification commands.

## Offline run

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\enrich_permits.py run --snapshot snapshots/pilot_20261014 --output runs/pilot_reproduced
.\.venv\Scripts\python.exe scripts\enrich_permits.py verify --snapshot snapshots/pilot_20261014 --output runs/pilot_reproduced
```

The CSV is `artifacts/runs/pilot_reproduced/permits_enriched.csv`. Always choose a new output directory. Snapshot/output arguments are relative to `artifacts/`; absolute arguments must also stay beneath that directory. Original input and output directories must be separate. Do not change frozen JSON or policy bytes to make verification pass.

The 47-location pilot is a regression dataset, not the final population. The older retained CSV under `artifacts/runs/20261014T213655293397Z` records an earlier policy; a current rerun has 45 matches and 2 unresolved street-name conflicts. Use newly generated results when assessing the current implementation.

## Live full capture

```powershell
.\.venv\Scripts\python.exe scripts\fetch_full.py --snapshot snapshots/new_full --eligible-types
.\.venv\Scripts\python.exe scripts\enrich_permits.py run --snapshot snapshots/new_full --output runs/new_full
.\.venv\Scripts\python.exe scripts\enrich_permits.py verify --snapshot snapshots/new_full --output runs/new_full
```

An interrupted capture can resume using `scripts\fetch_full.py --snapshot snapshots/new_full --resume --eligible-types`. Do not resume a completed delivery snapshot in place. The collector checks source counts/IDs, captures complete fields and additional application context, and retains date/type records for utility-name review. Inspect saved errors and exceptions before accepting results. A completed fetch does not mean every location matched.

The latest recorded local service probe on October 15, 2026 reached the occupancy and roadway endpoints but encountered LRS errors/timeouts. Recheck availability before a new full capture. Offline reproduction does not require those services.

## Configuration and assumptions

`DATE_SQL`, `START`, `END`, `TYPES` and `ALIASES` in `scripts/enrich_permits.py` implement the stated 2026 scope. Date SQL and Python boundaries must remain consistent. The collector and matcher use the documented 50 m/1 m policy; it is intentionally fixed for reproducibility. Changing scope or matching policy requires a new capture/result and matching tests. `config/case_resolutions.json` is hash-pinned historical evidence, not a place to adjust thresholds or add unreviewed aliases.

## Attach optional MAR evidence

To supplement unresolved conventional addresses after a completed LRS capture:

```powershell
.\.venv\Scripts\python.exe scripts\capture_mar.py --snapshot snapshots/new_full --output snapshots/new_full_mar
.\.venv\Scripts\python.exe scripts\enrich_permits.py run --snapshot snapshots/new_full_mar --output runs/new_full_mar
.\.venv\Scripts\python.exe scripts\enrich_permits.py verify --snapshot snapshots/new_full_mar --output runs/new_full_mar
```

The MAR collector queries only the public address-point and roadway layers; it does not call LRS. It copies the finalized base to a new directory and preserves its original hashes and manifest. A recorded query directory can instead be supplied with `--saved-queries PATH`. The included full submission snapshot already contains its evidence and reproduces offline. Standard same-class intersections can be classified from saved LRS/roadway files without MAR. The new class/method fields are described in [OUTPUT_FIELDS.md](OUTPUT_FIELDS.md).

## Build the submission

Use a verified full snapshot and a new absolute output destination:

```powershell
$destination = Join-Path (Get-Location).Path 'deliverables\python_submission'
.\.venv\Scripts\python.exe scripts\build_submission.py --snapshot snapshots/new_full --output runs/new_full --destination "$destination"
```

The ZIP contains the same `scripts/`, `tests/`, `docs/`, `config/` and `artifacts/` layout, its own README and dependency file, measured `REPORT.json`, and unresolved rows in `EXCEPTIONS.csv`. The builder verifies the selected result and checks required inputs before writing. Do not include `.venv`, caches, development logs or unrelated assessments.

Extract the ZIP to a new directory containing spaces. Create a fresh environment, install its root requirements, run its tests, verify the delivered CSV, then regenerate it into a new run directory and compare SHA-256 hashes with `Get-FileHash`. This validates the actual archive rather than only the working checkout. A representative test ZIP does not certify the final full-data ZIP.

## Before submitting

Review utility-looking excluded names, out-of-filter application locations, `MultiAddresses`, street-name conflicts and failed LRS lookups. Keep unresolved rows visible and describe limitations. The personal-name Python archive is `Yuhan_Wu_Python.zip` (no middle initial supplied). General guidance also requests a personal-name parent package, `Yuhan_Wu_CS12_DataScientist_Tests.zip`, containing the selected assessment archive(s). Submit using the assessment's supplied destination; publishing this repository is not that submission.

## Restored frozen delivery

The copied full capture has been reproduced and packaged using the current layout. See [delivery details](DELIVERY.md) for local paths, measured counts, archive checksums and extraction validation. Live LRS access is unnecessary for this retained result.

## Local parent archive generation

The repository contains the verified self-contained Python ZIP under `submission/`. If preparing the general-guidance personal-name parent archive, use a new destination:

```powershell
New-Item -ItemType Directory -Path .\deliverables\Yuhan_Wu -Force | Out-Null
Copy-Item -LiteralPath .\submission\Yuhan_Wu_Python.zip -Destination .\deliverables\Yuhan_Wu\Yuhan_Wu_Python.zip
Compress-Archive -LiteralPath .\deliverables\Yuhan_Wu -DestinationPath .\deliverables\Yuhan_Wu_CS12_DataScientist_Tests.zip
```

The locally verified final pair is in `deliverables/python_v5_readme_final`. Avoid selecting an older archive from another local run.
