"""Evidence provenance and independent verification of the complete v5 route."""
import copy
import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import enrich_permits as e
from scripts import capture_mar


class SupplementalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / 'snapshot'
        self.snapshot.mkdir()
        self.output = self.root / 'output'
        attrs = {'OBJECTID': 1, 'TrackingNumber': 10, 'LocationID': 100, 'ApplicationDate': e.START,
                 'IssueDate': None, 'ApplicantCompany': 'DCWater',
                 'EventTypeDescription': 'Construction Staging Area', 'MultiAddresses': None,
                 'WorkLocationFullAddress': '10 MAIN STREET NW'}
        feature = {'attributes': attrs, 'geometry': {'x': -77.0, 'y': 38.9}}
        nearest = {'subBlockKey': 'side', 'routeName': 'SIDE ST NW', 'routeType': 'Street',
                   'offsetInMeters': 1, 'unitBlock': '1 - 99 BLOCK OF SIDE STREET NW'}
        target = {'subBlockKey': 'main', 'routeName': 'MAIN ST NW', 'routeType': 'Street',
                  'offsetInMeters': 12, 'unitBlock': '1 - 99 BLOCK OF MAIN STREET NW'}
        roads = [{'attributes': {'SUBBLOCKKEY': 'side', 'ROUTENAME': 'SIDE ST NW', 'ROADTYPE': '1',
                                 'FHWAFUNCTIONALCLASS': 7}},
                 {'attributes': {'SUBBLOCKKEY': 'main', 'ROUTENAME': 'MAIN ST NW', 'ROADTYPE': '1',
                                 'FHWAFUNCTIONALCLASS': 4}}]
        e.save(self.snapshot / 'permits.json', {'metadata': {'fields': [{'name': k} for k in attrs]},
                                               'features': [feature], 'controls': []})
        e.save(self.snapshot / 'lrs.json', {e.point_key(feature): {'pointOnSubBlocks': [nearest, target]}})
        e.save(self.snapshot / 'roads.json', {'metadata': {'fields': [{'name': k} for k in roads[0]['attributes']]},
                                             'features': roads})
        manifest = {'selected_applications': [10], 'whole_application_object_ids': {'10': [1]},
                    'hashes': {name: e.digest(self.snapshot / name)
                               for name in ('permits.json', 'lrs.json', 'roads.json')}}
        e.save(self.snapshot / 'base_manifest.json', manifest)
        address = {'attributes': {'ADDRESS': '10 MAIN STREET NW', 'STATUS': 'ACTIVE',
                                   'SUBBLOCKKEY': 'main', 'MAR_ID': 123}}
        queries = [{'url': url + '/query', 'params': {'outSR': 4326, 'returnGeometry': 'true'},
                    'retrieved_utc': '2026-10-16T02:00:00+00:00', 'response': {'features': values}}
                   for url, values in [(e.MAR, [address]), (e.ROADS, [roads[1]])]]
        evidence = {'source_url': e.MAR, 'road_source_url': e.ROADS,
                    'base_snapshot_sha256': e.digest(self.snapshot / 'base_manifest.json'),
                    'queries': queries, 'address_features': [address], 'road_features': [roads[1]]}
        e.save(self.snapshot / 'mar_evidence.json', evidence)
        manifest['hashes'].update({name: e.digest(self.snapshot / name)
                                  for name in ('base_manifest.json', 'mar_evidence.json')})
        e.save(self.snapshot / 'manifest.json', manifest)

    def save_evidence(self, evidence):
        e.save(self.snapshot / 'mar_evidence.json', evidence)
        manifest = e.load(self.snapshot / 'manifest.json')
        manifest['hashes']['mar_evidence.json'] = e.digest(self.snapshot / 'mar_evidence.json')
        e.save(self.snapshot / 'manifest.json', manifest)

    def rows(self):
        with (self.output / 'permits_enriched.csv').open(encoding='utf-8', newline='') as stream:
            return list(csv.DictReader(stream))

    def test_end_to_end_and_verifier_does_not_call_producer(self):
        e.run(self.snapshot, self.output)
        row = self.rows()[0]
        self.assertEqual((row['enrich_fhwa_code'], row['enrich_class_method'],
                          row['enrich_subblock_key'], row['enrich_application_highest_code']),
                         ('4', 'mar_address', 'main', '4'))
        self.assertEqual(json.loads(row['enrich_supporting_subblock_keys']), ['main'])
        with patch.object(e, 'match', side_effect=AssertionError('producer called')), \
                patch.object(e.supplemental, 'apply', side_effect=AssertionError('supplement called')):
            e.verify(self.snapshot, self.output)

    def test_rehashed_fabricated_support_is_rejected(self):
        e.run(self.snapshot, self.output)
        rows = self.rows()
        rows[0]['enrich_supporting_subblock_keys'] = '["invented"]'
        path = self.output / 'permits_enriched.csv'
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        report = e.load(self.output / 'manifest.json')
        report['csv_sha256'] = e.digest(path)
        e.save(self.output / 'manifest.json', report)
        with self.assertRaisesRegex(ValueError, 'supporting_subblock_keys'):
            e.verify(self.snapshot, self.output)

    def test_flattened_response_cannot_disagree_with_raw_evidence(self):
        evidence = e.load(self.snapshot / 'mar_evidence.json')
        evidence['road_features'][0]['attributes']['FHWAFUNCTIONALCLASS'] = 3
        self.save_evidence(evidence)
        with self.assertRaisesRegex(ValueError, 'differs from raw queries'):
            e.run(self.snapshot, self.output)

    def test_current_class_drift_keeps_original_case_unresolved(self):
        evidence = e.load(self.snapshot / 'mar_evidence.json')
        evidence['road_features'][0]['attributes']['FHWAFUNCTIONALCLASS'] = 3
        evidence['queries'][1]['response']['features'] = copy.deepcopy(evidence['road_features'])
        self.save_evidence(evidence)
        e.run(self.snapshot, self.output)
        self.assertEqual(self.rows()[0]['enrich_match_status'], 'unresolved')
        self.assertEqual(self.rows()[0]['enrich_application_highest_code'], '')
        e.verify(self.snapshot, self.output)

    def test_unhashed_or_wrong_source_evidence_fails_closed(self):
        manifest = e.load(self.snapshot / 'manifest.json')
        del manifest['hashes']['mar_evidence.json']
        e.save(self.snapshot / 'manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'Unhashed or missing'):
            e.run(self.snapshot, self.output)
        evidence = e.load(self.snapshot / 'mar_evidence.json')
        evidence['source_url'] = 'https://example.invalid/'
        self.save_evidence(evidence)
        with self.assertRaisesRegex(ValueError, 'Unexpected supplemental source'):
            e.run(self.snapshot, self.output)

    def test_saved_capture_is_an_immutable_copy_and_reproduces_without_network(self):
        original = self.root / 'original'
        original.mkdir()
        for name in ('permits.json', 'lrs.json', 'roads.json'):
            shutil.copy2(self.snapshot / name, original / name)
        shutil.copy2(self.snapshot / 'base_manifest.json', original / 'manifest.json')
        (original / '.fetch_complete').touch()
        before = e.digest(original / 'manifest.json')
        raw = self.root / 'raw'
        raw.mkdir()
        records = e.load(self.snapshot / 'mar_evidence.json')['queries']
        for name, record in zip(('mar_addresses_0.json', 'mar_roads_0.json'), records):
            e.save(raw / name, record)
        attached = self.root / 'attached'
        with patch.object(e, 'client', side_effect=AssertionError('network called')):
            capture_mar.capture(original, attached, raw)
        self.assertEqual(e.digest(original / 'manifest.json'), before)
        self.assertEqual(e.digest(attached / 'permits.json'), e.digest(original / 'permits.json'))
        self.assertTrue((attached / '.fetch_complete').is_file())
        e.run(attached, self.output)
        e.verify(attached, self.output)
        self.assertEqual(self.rows()[0]['enrich_class_method'], 'mar_address')


if __name__ == '__main__':
    unittest.main()
