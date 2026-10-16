# CS12 Python Assessment

Enrich DC utility occupancy permit locations with roadway FHWA functional classes and the highest class for each complete application.

**[Final enriched CSV](results/permits_enriched.csv)** · [Unresolved locations](results/EXCEPTIONS.csv) · [Counts and provenance](results/REPORT.json)

The CSV is also available directly at `results/permits_enriched.csv` after cloning. It is byte-identical to the CSV inside the full-data ZIP.

The repository includes source, tests, a small regression pilot, and the **complete standalone full-data ZIP** at [submission/Yuhan_Wu_Python.zip](submission/Yuhan_Wu_Python.zip). That archive contains the frozen full capture, retained MAR evidence, final CSV, exceptions, scripts, requirements and reproduction instructions.

## Clone and install — Windows

Requires Git and Python 3.10+; tested on Windows 11 with Python 3.11. The repository is private during the assessment and is planned to become public after the submission deadline. Until publication, Git must authenticate with an account that has access. The standalone ZIP runs independently of GitHub access.

Open PowerShell in any writable parent folder:

```powershell
git clone https://github.com/YuhanMax/cs12-data-scientist-assessment.git
cd cs12-data-scientist-assessment
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If using another supported installed Python, replace `py -3.11` with its launcher command. Activation is optional; ArcGIS Pro and MAR credentials are not required. Dependency installation needs internet access or preinstalled dependency wheels.

## Test and run the small pilot

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\enrich_permits.py run --snapshot snapshots/pilot_20261014 --output runs/my_run
.\.venv\Scripts\python.exe scripts\enrich_permits.py verify --snapshot snapshots/pilot_20261014 --output runs/my_run
```

Choose a new output name on each run. The frozen pilot has 47 locations across 24 applications: 45 assigned classes and 2 unresolved street-name disagreements. Its source snapshot/output arguments resolve beneath this checkout's `artifacts/`.

## Reproduce the full frozen result offline

After installing requirements, run these commands from the repository root. Use an unused extraction directory and an unused reproduced output name:

```powershell
Get-FileHash .\submission\Yuhan_Wu_Python.zip -Algorithm SHA256
Expand-Archive -LiteralPath .\submission\Yuhan_Wu_Python.zip -DestinationPath .\tmp\submission_check
.\.venv\Scripts\python.exe .\tmp\submission_check\Yuhan_Wu_Python\scripts\enrich_permits.py verify --snapshot snapshots/full_20261014_mar_v5 --output runs/final_mar_v5
.\.venv\Scripts\python.exe .\tmp\submission_check\Yuhan_Wu_Python\scripts\enrich_permits.py run --snapshot snapshots/full_20261014_mar_v5 --output runs/reproduced
.\.venv\Scripts\python.exe .\tmp\submission_check\Yuhan_Wu_Python\scripts\enrich_permits.py verify --snapshot snapshots/full_20261014_mar_v5 --output runs/reproduced
Get-FileHash .\tmp\submission_check\Yuhan_Wu_Python\artifacts\runs\final_mar_v5\permits_enriched.csv, .\tmp\submission_check\Yuhan_Wu_Python\artifacts\runs\reproduced\permits_enriched.csv -Algorithm SHA256
```

Compare the ZIP hash with [SHA256SUMS.txt](submission/SHA256SUMS.txt). The two CSV hashes must agree. Snapshot/output arguments in this section resolve beneath the **extracted package's** `artifacts/`, because they are anchored to its script location. These checks do not call live services. For a completely separate environment, open the extracted folder and follow its own README.

## Layout

| Path | Purpose |
| --- | --- |
| `scripts/` | Capture, MAR evidence, enrichment/verification and ZIP builder |
| `tests/` | Offline regression and packaging tests |
| `docs/` | Usage, methodology, output fields, assessment checklist and validation |
| `config/` | Hash-pinned historical pilot policy |
| `artifacts/` | Versioned small pilot plus ignored local captures and runs |
| `results/` | Direct final CSV, unresolved rows, report and checksums |
| `submission/` | Verified standalone full-data Python ZIP, checksum and validation record |
| `deliverables/` | Generated local parent archives and rebuilds, excluded from Git |
| `requirements.txt` | Single dependency list |

## Result and limits

The captured cohort has **4,983 locations in 3,129 applications: 4,927 assigned FHWA classes and 56 unresolved locations**. Version 5 adds 89 exact-address MAR assignments and 10 intersection class-consensus outcomes. The original source fields, geometry and previously accepted road/class assignments are preserved. A class-consensus intersection retains supporting keys and has no asserted unique subblock.

The actual Python ZIP passed 59 tests in a fresh Windows extraction and reproduced the full CSV byte for byte. The result is 2026 to date and remains a documented partial enrichment, as allowed by the assessment. Unresolved locations and incomplete application maxima remain blank. See [delivery details](docs/DELIVERY.md), [assessment checklist](docs/ASSESSMENT_CHECKLIST.md), [usage](docs/USAGE.md), [methodology](docs/METHODOLOGY.md), [output fields](docs/OUTPUT_FIELDS.md) and [exception review](docs/EXCEPTION_REVIEW.md).
