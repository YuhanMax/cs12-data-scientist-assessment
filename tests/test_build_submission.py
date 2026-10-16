"""Checks for the standalone Python archive and its measured report."""
import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_submission as b


class SubmissionTests(unittest.TestCase):
    def package_fixture(self, root):
        snapshot = root / 'snapshots/current'
        output = root / 'runs/current'
        pilot = root / 'snapshots/pilot_20261014'
        for directory in (snapshot, output, pilot):
            directory.mkdir(parents=True)
        b.e.save(snapshot / 'manifest.json', {})
        b.e.save(snapshot / 'date_type_cohort.json', {'features': []})
        for name in ('permits.json', 'lrs.json', 'roads.json', 'application_context.json'):
            b.e.save(snapshot / name, {})
        (snapshot / '.fetch_complete').touch()
        for name in ('manifest.json', 'permits.json', 'lrs.json', 'roads.json'):
            b.e.save(pilot / name, {})
        (pilot / '.fetch_complete').touch()
        b.e.save(output / 'manifest.json', {'enrichment_prefix': 'enrich_', 'locations': 0, 'applications': 0})
        with (output / 'permits_enriched.csv').open('w', newline='', encoding='utf-8') as stream:
            csv.writer(stream).writerow(['TrackingNumber', 'enrich_match_status'])
        original = root / 'runs/20261014T213655293397Z'
        original.mkdir(parents=True)
        b.e.save(original / 'manifest.json', {})
        return snapshot, output

    def test_package_contains_only_python_reproduction_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, output = self.package_fixture(root)
            with patch.object(b.e, 'ROOT', root), patch.object(b.e, 'verify'):
                archive = b.build(snapshot, output, root / 'package')
            with zipfile.ZipFile(archive) as package:
                names = set(package.namelist())
                readme = package.read(b.NAME + '/README.md').decode('utf-8')
                report = json.loads(package.read(b.NAME + '/REPORT.json'))
                evidence = package.read(b.NAME + '/docs/ANOMALY_EVIDENCE.md').decode('utf-8')
            for name in b.PROGRAM_FILES:
                self.assertIn(b.NAME + '/' + name, names)
            self.assertIn(b.NAME + '/artifacts/snapshots/current/permits.json', names)
            self.assertIn(b.NAME + '/artifacts/runs/current/permits_enriched.csv', names)
            self.assertIn(b.NAME + '/artifacts/snapshots/pilot_20261014/.fetch_complete', names)
            self.assertIn(b.NAME + '/artifacts/runs/20261014T213655293397Z/manifest.json', names)
            self.assertIn(b.NAME + '/EXCEPTIONS.csv', names)
            self.assertIn('SUBBLOCKKEY', evidence)
            self.assertIn('--snapshot snapshots/current', readme)
            self.assertEqual(report['locations'], 0)
            self.assertFalse(any('/qa_optional/' in name or '/gis/' in name or '/anomalies/' in name
                                 for name in names))
            self.assertFalse(any(name.endswith('/FINAL_REVIEW.md') or name.endswith('/VALIDATION.md')
                                 or name.endswith('/METHODOLOGY_FIX_REVIEW.md') for name in names))

    def test_missing_reproduction_input_rejected_before_destination_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, output = self.package_fixture(root)
            (snapshot / 'application_context.json').unlink()
            with patch.object(b.e, 'ROOT', root), patch.object(b.e, 'verify'):
                with self.assertRaisesRegex(ValueError, 'Missing package dependency:.*application_context.json'):
                    b.build(snapshot, output, root / 'package')
            self.assertFalse((root / 'package').exists())

    def test_runtime_identity_audit_and_explicit_zero_types(self):
        cohort = {'features': [
            {'attributes': {'OBJECTID': 1, 'ApplicantCompany': 'DCWater'}},
            {'attributes': {'OBJECTID': 2, 'ApplicantCompany': 'Other', 'OwnerName': 'WASHINGTON GAS'}},
            {'attributes': {'OBJECTID': 3, 'ApplicantCompany': 'Other', 'PermitteeName': 'PEPCO'}},
            {'attributes': {'OBJECTID': 4, 'ApplicantCompany': 'Waterproofing'}}]}
        rows = [{'ApplicantCompany': 'DCWater', 'EventTypeDescription': 'Construction Staging Area',
                 'TrackingNumber': '11', 'enrich_application_complete': 'False', 'enrich_fhwa_code': '',
                 'enrich_match_status': 'unresolved', 'enrich_match_reason': 'service_error'}]
        report = b.audit(cohort, rows, 'enrich_')
        self.assertEqual(report['requested_type_counts']['Mobile Crane Work Zone'], 0)
        self.assertEqual(report['utility_alias_counts']['DCWater'], 1)
        self.assertEqual(report['utility_counts']['PEPCO'], 0)
        self.assertEqual([r['OBJECTID'] for r in report['unmatched_utility_looking_identities']], [2, 3])
        self.assertEqual(report['exception_counts'], {'service_error': 1})
        self.assertEqual((report['complete_applications'], report['incomplete_applications']), (0, 1))

    def test_existing_destination_refused_after_verification(self):
        with patch.object(b.e, 'verify') as verify:
            with self.assertRaisesRegex(ValueError, 'new absolute directory'):
                b.build(Path('snapshot'), Path('output'), Path(__file__).parent.resolve())
        verify.assert_called_once()


if __name__ == '__main__':
    unittest.main()
