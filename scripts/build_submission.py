"""Build a verified, standalone Python assessment archive."""
import argparse
import csv
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

if __package__:
    from . import enrich_permits as e
else:
    import enrich_permits as e

HERE = Path(__file__).resolve().parent.parent
NAME = 'Yuhan_Wu_Python'
UTILITY_LOOKING = re.compile(r'DC\s*WATER|PEPCO|POTOMAC\s+ELECTRIC|WASH(?:INGTON)?\s+GAS', re.I)
PROGRAM_FILES = (
    'requirements.txt',
    'scripts/__init__.py', 'scripts/enrich_permits.py',
    'scripts/fetch_full.py', 'scripts/build_submission.py', 'scripts/capture_mar.py',
    'scripts/supplemental.py', 'scripts/supplemental_verify.py',
    'tests/__init__.py', 'tests/test_enrich_permits.py',
    'tests/test_fetch_full.py', 'tests/test_build_submission.py',
    'tests/test_address_conflicts.py', 'tests/test_snapshot_validation.py',
    'tests/test_supplemental.py', 'tests/test_supplemental_verify.py',
    'tests/test_supplemental_integration.py',
    'config/case_resolutions.json',
    'docs/METHODOLOGY.md', 'docs/ANOMALY_EVIDENCE.md', 'docs/OUTPUT_FIELDS.md',
)
SNAPSHOT_FILES = (
    'manifest.json', 'permits.json', 'lrs.json', 'roads.json',
    'date_type_cohort.json', 'application_context.json', '.fetch_complete',
)
PILOT_FILES = ('manifest.json', 'permits.json', 'lrs.json', 'roads.json', '.fetch_complete')
OUTPUT_FILES = ('manifest.json', 'permits_enriched.csv')


def audit(cohort, rows, prefix):
    features = cohort['features']
    applications = {r['TrackingNumber'] for r in rows}
    complete_applications = {r['TrackingNumber'] for r in rows if r[prefix + 'application_complete'] == 'True'}
    aliases = {alias: sum(f['attributes'].get('ApplicantCompany') == alias for f in features)
               for alias in e.ALIASES}
    types = {kind: sum(r['EventTypeDescription'] == kind for r in rows) for kind in sorted(e.TYPES)}
    identities = []
    for feature in features:
        attrs = feature['attributes']
        if attrs.get('ApplicantCompany') in e.ALIASES:
            continue
        identity = {key: attrs.get(key) for key in
                    ('OBJECTID', 'TrackingNumber', 'LocationID', 'ApplicantCompany', 'OwnerName', 'PermitteeName')}
        if any(UTILITY_LOOKING.search(str(identity.get(key) or ''))
               for key in ('ApplicantCompany', 'OwnerName', 'PermitteeName')):
            identities.append(identity)
    return {'captured_date_type_locations': len(features), 'utility_alias_counts': aliases,
            'utility_counts': {utility: sum(e.ALIASES[r['ApplicantCompany']] == utility for r in rows)
                               for utility in sorted(set(e.ALIASES.values()))},
            'requested_type_counts': types,
            'captured_date_type_counts': {kind: sum(f['attributes'].get('EventTypeDescription') == kind
                                                   for f in features) for kind in sorted(e.TYPES)},
            'unmatched_utility_looking_identities': identities,
            'identity_audit_scope': '2026 date-OR/type cohort; company, owner and permittee; regex heuristic only',
            'complete_applications': len(complete_applications),
            'incomplete_applications': len(applications - complete_applications),
            'match_counts': dict(Counter(r[prefix + 'match_status'] for r in rows)),
            'match_reason_counts': dict(Counter(r[prefix + 'match_reason'] for r in rows)),
            'class_method_counts': dict(Counter(r.get(prefix + 'class_method') or 'unresolved' for r in rows)),
            'matched_fhwa_counts': dict(Counter(r[prefix + 'fhwa_code'] for r in rows
                                               if r[prefix + 'match_status'] == 'matched')),
            'exception_counts': dict(Counter(r[prefix + 'match_reason'] for r in rows
                                           if r[prefix + 'match_status'] != 'matched')),
            'unresolved_locations': sum(r[prefix + 'match_status'] != 'matched' for r in rows)}


def readme(snapshot_relative, output_relative, source, result, report, extra_output_files=()):
    locations = {
        'Final enriched CSV': f'artifacts/{output_relative}/permits_enriched.csv',
        'Unresolved locations': 'EXCEPTIONS.csv',
        'Scope, counts and evidence provenance': 'REPORT.json',
        'Delivered result manifest': f'artifacts/{output_relative}/manifest.json',
        'Enrichment and independent verification entry point': 'scripts/enrich_permits.py',
        'Fresh source capture': 'scripts/fetch_full.py',
        'Optional MAR evidence capture': 'scripts/capture_mar.py',
        'Archive builder': 'scripts/build_submission.py',
        'Supplemental matching': 'scripts/supplemental.py',
        'Independent supplemental verifier': 'scripts/supplemental_verify.py',
        'Regression tests': 'tests/',
        'Dependencies': 'requirements.txt',
        'Methodology': 'docs/METHODOLOGY.md',
        'Output field dictionary': 'docs/OUTPUT_FIELDS.md',
        'Historical pilot policy': 'config/case_resolutions.json',
    }
    for name in SNAPSHOT_FILES:
        locations['Frozen input: ' + name] = f'artifacts/{snapshot_relative}/{name}'
    if report.get('supplemental_evidence'):
        for name in ('base_manifest.json', 'mar_evidence.json'):
            locations['Supplementary evidence: ' + name] = f'artifacts/{snapshot_relative}/{name}'
    for name in extra_output_files:
        locations['Additional result: ' + name] = f'artifacts/{output_relative}/{name}'
    file_table = '\n'.join(f'| {label} | [{path}]({path}) |' for label, path in locations.items())
    file_list = '\n'.join("    '" + path + "'" for path in locations.values())
    text = f'''# CS12 Python Assessment

Author: Yuhan Wu.

Enrich DC utility occupancy permit locations with roadway FHWA functional classes and the highest class for each complete application.

Requires Python 3.10+ on Windows 11. Requests is the sole direct dependency.

## Results

- [Open the final enriched CSV](artifacts/{output_relative}/permits_enriched.csv)
- [Review unresolved locations](EXCEPTIONS.csv)
- [View counts and provenance](REPORT.json)

| Result | Count |
| --- | ---: |
| Permit locations | {result['locations']:,} |
| Applications | {result['applications']:,} |
| Locations with an assigned FHWA class | {result['locations'] - report['unresolved_locations']:,} |
| Unresolved locations | {report['unresolved_locations']:,} |

The result is a documented partial enrichment; unresolved locations remain visible.

To review the delivery, open the CSV and exception list above. To check or reproduce
it, follow **Reproduce the saved result offline** below. Fresh-data capture and
the source repository are optional.

## File locations and complete paths

Extract the archive and open the `Yuhan_Wu_Python` folder containing this README.
The paths below start at that folder and name the included files explicitly.

Final CSV path from the extracted folder:

```text
artifacts/{output_relative}/permits_enriched.csv
```

<details>
<summary>All included file paths and commands to list their absolute locations</summary>

| File purpose | Complete path within the extracted package |
| --- | --- |
{file_table}

For example, if extracted to `C:/Assessment/Yuhan_Wu_Python`, the final CSV is
`C:/Assessment/Yuhan_Wu_Python/artifacts/{output_relative}/permits_enriched.csv`.
To print the actual full absolute paths on your computer, run this from the folder
containing this README. `Exists` should be `True` for every entry:

```powershell
$packageRoot = (Get-Location).Path
$requiredFiles = @(
{file_list}
)
$requiredFiles | ForEach-Object {{
    $resolvedFile = Join-Path -Path $packageRoot -ChildPath $_
    [pscustomobject]@{{ File = $_; FullPath = $resolvedFile; Exists = (Test-Path -LiteralPath $resolvedFile) }}
}} | Format-List
```

</details>

## Reproduce the saved result offline

Open PowerShell in this extracted folder and run:

```powershell
py -3.11 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p 'test*.py' -v
.\\.venv\\Scripts\\python.exe scripts\\enrich_permits.py verify --snapshot {snapshot_relative} --output {output_relative}
.\\.venv\\Scripts\\python.exe scripts\\enrich_permits.py run --snapshot {snapshot_relative} --output runs/reproduced
.\\.venv\\Scripts\\python.exe scripts\\enrich_permits.py verify --snapshot {snapshot_relative} --output runs/reproduced
Get-FileHash artifacts\\{output_relative.replace('/', chr(92))}\\permits_enriched.csv, artifacts\\runs\\reproduced\\permits_enriched.csv -Algorithm SHA256
```

Use a new output name if `runs/reproduced` exists. Relative snapshot and output paths
resolve under this folder's `artifacts` directory. The two CSV hashes should match.

The original source values, geometry and raw service responses are retained in the snapshot.

## Data and outputs

- **Final CSV:** [permits_enriched.csv](artifacts/{output_relative}/permits_enriched.csv), with {result['locations']:,} locations in {result['applications']:,} applications.
- **Application coverage:** {report['complete_applications']:,} class-complete applications; {report['unresolved_locations']:,} unresolved locations remain visible.
- **Summary and provenance:** [REPORT.json](REPORT.json) records utility, permit-type and exception counts.
- **Outstanding cases:** [EXCEPTIONS.csv](EXCEPTIONS.csv) contains every unresolved row.

- **Snapshot finalized (UTC):** {source.get('retrieved_utc', 'time not recorded')}.
- **Permit retrieval started (UTC):** {source.get('source_retrieval_started_utc', 'time not recorded')}.
- **Permit retrieval finished (UTC):** {source.get('source_retrieval_finished_utc', 'time not recorded')}.

This is a 2026-to-date public-source capture, not a completed annual census.
Later MAR evidence, when present, is hashed inside the selected snapshot; its
individual retrieval times and base-capture hash are listed in REPORT.json.

## Method and limits

The source filter uses application date OR issue date within the 2026 America/New_York
calendar year, the two requested permit types, and six exact applicant-company aliases.
LRS supplies nearest eligible roadway candidates; roadway layer 162 supplies FHWA classes.

Version 5 also uses exact ACTIVE MAR addresses when their referenced road is a consistent
frozen candidate within 50 m. At standard two-street intersections, matching FHWA classes
across all near-tie candidates can determine the class without selecting a unique subblock.
`class_method` and `supporting_subblock_keys` distinguish these outcomes; a class-consensus
row has blank unique-road fields. Different-class intersections remain unresolved.

Alleys are excluded. A lower valid FHWA code ranks higher. Unresolved locations remain
in the CSV; incomplete applications have a blank `application_highest_code/name`.

The match is an auditable nearest-road approximation, not a field-confirmed association.
The utility aliases and live service availability may also limit coverage.

See [methodology](docs/METHODOLOGY.md) for the matching rules and
[output fields](docs/OUTPUT_FIELDS.md) for column meanings. The
[pilot evidence](docs/ANOMALY_EVIDENCE.md) explains the pinned historical decision.

## Capture fresh data

```powershell
.\\.venv\\Scripts\\python.exe scripts\\fetch_full.py --snapshot snapshots/new_full --eligible-types
.\\.venv\\Scripts\\python.exe scripts\\enrich_permits.py run --snapshot snapshots/new_full --output runs/new_full
.\\.venv\\Scripts\\python.exe scripts\\enrich_permits.py verify --snapshot snapshots/new_full --output runs/new_full
```

Live captures can differ from the included frozen result. Use a new snapshot name;
`scripts/fetch_full.py --snapshot snapshots/new_full --resume --eligible-types`
resumes an interrupted capture. For optional MAR supplements, copy a finalized capture
to a new evidenced snapshot with:

```powershell
.\\.venv\\Scripts\\python.exe scripts\\capture_mar.py --snapshot snapshots/new_full --output snapshots/new_full_mar
.\\.venv\\Scripts\\python.exe scripts\\enrich_permits.py run --snapshot snapshots/new_full_mar --output runs/new_full_mar
.\\.venv\\Scripts\\python.exe scripts\\enrich_permits.py verify --snapshot snapshots/new_full_mar --output runs/new_full_mar
```

These optional commands need the public MAR and roadway services, but do not repeat LRS calls.
Inspect the exception rows and REPORT.json before reporting a new result.

## Source repository (optional)

The complete frozen inputs and delivered output are already included in this ZIP.

The repository is private during the assessment and is planned to become public
after the submission deadline. Until publication, cloning requires an account with
repository access. To obtain the source checkout separately:

```powershell
git clone https://github.com/YuhanMax/cs12-data-scientist-assessment.git
cd cs12-data-scientist-assessment
```

The repository README describes setup and the bundled full-data ZIP under `submission/`.
Git and a GitHub account are not needed to run this extracted package.
'''
    # Keep prose on one source line per paragraph: some Markdown viewers render
    # soft source newlines as visible breaks. Preserve lists, tables and code.
    blocks = text.split('\n\n')
    in_code = False
    for index, block in enumerate(blocks):
        if block.startswith('```') or in_code:
            if block.count('```') % 2:
                in_code = not in_code
            continue
        if block.startswith(('#', '|', '-', '<')):
            continue
        blocks[index] = ' '.join(block.splitlines())
    return '\n\n'.join(blocks)


def require_files(paths):
    missing = [str(path) for path in paths if not path.is_file()]
    e.require(not missing, 'Missing package dependency: ' + ', '.join(missing))


def build(snapshot, output, destination):
    e.verify(snapshot, output)
    e.require(destination.is_absolute() and not destination.exists(),
              '--destination must be a new absolute directory')
    pilot = e.ROOT / 'snapshots/pilot_20261014'
    original = e.ROOT / 'runs/20261014T213655293397Z/manifest.json'
    required = ([HERE / name for name in PROGRAM_FILES] +
                [snapshot / name for name in SNAPSHOT_FILES] +
                [output / name for name in OUTPUT_FILES] +
                [pilot / name for name in PILOT_FILES] + [original])
    require_files(required)
    snapshot_relative = snapshot.relative_to(e.ROOT).as_posix()
    output_relative = output.relative_to(e.ROOT).as_posix()
    source = e.load(snapshot / 'manifest.json')
    result = e.load(output / 'manifest.json')
    cohort = e.load(snapshot / 'date_type_cohort.json')
    with (output / 'permits_enriched.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    report = audit(cohort, rows, result['enrichment_prefix'])
    report.update(author='Yuhan Wu', snapshot_manifest_sha256=e.digest(snapshot / 'manifest.json'),
                  locations=result['locations'], applications=result['applications'],
                  match_policy=e.MATCH_POLICY,
                  source_retrieval={key: value for key, value in source.items()
                                    if 'utc' in key or 'interval' in key},
                  )
    evidence = e.supplemental_evidence(snapshot)
    if evidence:
        report['supplemental_evidence'] = {
            'file': 'mar_evidence.json', 'sha256': e.digest(snapshot / 'mar_evidence.json'),
            'base_snapshot_sha256': evidence['base_snapshot_sha256'],
            'query_retrieval_times': sorted({q['retrieved_utc'] for q in evidence['queries']}),
            'address_records': len(evidence['address_features']),
            'road_records': len(evidence['road_features'])}
    files = {name: (HERE / name).read_bytes() for name in PROGRAM_FILES}
    extras = sorted(path.name for path in output.iterdir() if path.is_file()
                    and path.suffix in {'.json', '.csv'} and path.name not in OUTPUT_FILES)
    # Windows text viewers and Markdown renderers both need a readable README.
    readme_text = readme(snapshot_relative, output_relative, source, result, report, extras)
    files['README.md'] = readme_text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8')
    files['REPORT.json'] = json.dumps(report, indent=2, ensure_ascii=False).encode('utf-8')
    exceptions = io.StringIO(newline='')
    writer = csv.DictWriter(exceptions, fieldnames=fields)
    writer.writeheader()
    writer.writerows(r for r in rows if r[result['enrichment_prefix'] + 'match_status'] != 'matched')
    files['EXCEPTIONS.csv'] = exceptions.getvalue().encode('utf-8')
    for directory in (snapshot, output, pilot):
        for path in sorted(directory.rglob('*')):
            if path.is_file() and (path.suffix in {'.json', '.csv'} or path.name == '.fetch_complete'):
                files['artifacts/' + path.relative_to(e.ROOT).as_posix()] = path.read_bytes()
    files['artifacts/' + original.relative_to(e.ROOT).as_posix()] = original.read_bytes()
    destination.mkdir(parents=True)
    archive = destination / (NAME + '.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as package:
        for name, content in sorted(files.items()):
            package.writestr(NAME + '/' + name, content)
    print(f'Built {archive} ({len(files)} files; SHA256 {e.digest(archive)})')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    build(e.checked_path(args.snapshot), e.checked_path(args.output), Path(args.destination))
