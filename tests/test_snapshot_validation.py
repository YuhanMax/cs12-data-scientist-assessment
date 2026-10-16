import copy
import tempfile
import unittest
from pathlib import Path

from scripts import enrich_permits as app


class SnapshotValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.snapshot = Path(self.temporary.name)
        self.features = []
        for oid, company in [(1, 'DCWater'), (2, 'DCWater'), (3, 'Other')]:
            self.features.append({'attributes': {'OBJECTID': oid, 'TrackingNumber': oid,
                'LocationID': oid, 'ApplicationDate': app.START, 'IssueDate': None,
                'ApplicantCompany': company, 'EventTypeDescription': 'Construction Staging Area'},
                'geometry': {'x': -77 + oid / 1000, 'y': 38.9}})
        self.source = {'metadata': {'fields': [{'name': k} for k in self.features[0]['attributes']]},
                       'features': copy.deepcopy(self.features[:2]),
                       'controls': [{'reason': 'utility', 'feature': copy.deepcopy(self.features[2])}]}
        app.save(self.snapshot / 'permits.json', self.source)
        app.save(self.snapshot / 'date_type_cohort.json', {'features': self.features})
        app.save(self.snapshot / 'lrs.json', {app.point_key(f): {'pointOnSubBlocks': []}
                                            for f in self.source['features']})
        app.save(self.snapshot / 'roads.json', {'metadata': {'fields': [{'name': k} for k in
                 ['SUBBLOCKKEY', 'ROADTYPE', 'FHWAFUNCTIONALCLASS']]}, 'features': []})
        self.manifest = {'selection': 'complete exact FILTER cohort', 'selected_applications': [1, 2],
                         'whole_application_object_ids': {'1': [1], '2': [2]}, 'hashes': {}}
        self.rehash()

    def rehash(self):
        self.manifest['hashes'] = {p.name: app.digest(p) for p in self.snapshot.glob('*.json')
                                   if p.name != 'manifest.json'}
        app.save(self.snapshot / 'manifest.json', self.manifest)

    def test_success_false_ordinary_response_rejected(self):
        app.save(self.snapshot / 'lrs.json', {app.point_key(self.features[0]):
                 {'Success': False, 'Message': 'failed', 'pointOnSubBlocks': [
                     {'routeType': 'Street', 'subBlockKey': 'road', 'offsetInMeters': 1}]}})
        self.rehash()
        with self.assertRaisesRegex(ValueError, 'API error'):
            app.inputs(self.snapshot)

    def test_explicit_service_failures_and_legacy_pilot_remain_supported(self):
        app.save(self.snapshot / 'lrs.json', {'a': {'error': 'HTTP 503'}, 'b': {'unavailable': True}})
        self.rehash()
        app.inputs(self.snapshot)
        del self.manifest['selection']
        del self.manifest['hashes']['date_type_cohort.json']
        (self.snapshot / 'date_type_cohort.json').unlink()
        app.save(self.snapshot / 'manifest.json', self.manifest)
        app.inputs(self.snapshot)

    def test_self_consistent_permit_omission_rejected(self):
        self.source['features'].pop()
        self.manifest['selected_applications'] = [1]
        self.manifest['whole_application_object_ids'] = {'1': [1]}
        app.save(self.snapshot / 'permits.json', self.source)
        self.rehash()
        with self.assertRaisesRegex(ValueError, 'cohort'):
            app.inputs(self.snapshot)

    def test_full_feature_values_and_control_partition_rejected(self):
        original = copy.deepcopy(self.source)
        for mutation in ('attribute', 'geometry', 'control', 'control_geometry', 'duplicate'):
            with self.subTest(mutation=mutation):
                self.source = copy.deepcopy(original)
                if mutation == 'attribute':
                    self.source['features'][0]['attributes']['LocationID'] = 99
                elif mutation == 'geometry':
                    self.source['features'][0]['geometry']['x'] += 1
                elif mutation == 'control':
                    self.source['controls'] = []
                elif mutation == 'control_geometry':
                    self.source['controls'][0]['feature']['geometry']['y'] += 1
                else:
                    self.source['features'].append(copy.deepcopy(self.source['features'][0]))
                app.save(self.snapshot / 'permits.json', self.source)
                self.rehash()
                with self.assertRaisesRegex(ValueError, 'cohort|Duplicate'):
                    app.inputs(self.snapshot)

    def test_duplicate_cohort_oid_rejected(self):
        app.save(self.snapshot / 'date_type_cohort.json', {'features': self.features + [self.features[0]]})
        self.rehash()
        with self.assertRaisesRegex(ValueError, 'Duplicate date/type cohort OBJECTID'):
            app.inputs(self.snapshot)

    def test_declared_cohort_must_be_present_and_hashed(self):
        del self.manifest['hashes']['date_type_cohort.json']
        app.save(self.snapshot / 'manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'cohort'):
            app.inputs(self.snapshot)
        (self.snapshot / 'date_type_cohort.json').unlink()
        with self.assertRaisesRegex(ValueError, 'cohort'):
            app.inputs(self.snapshot)


if __name__ == '__main__':
    unittest.main()
