import csv
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import enrich_permits as app


class PilotTests(unittest.TestCase):
    def feature(self, tracking=1, location=1):
        return {'attributes': {'OBJECTID': location, 'TrackingNumber': tracking, 'LocationID': location,
                'PermitNumber': None, 'ApplicationDate': app.START, 'IssueDate': None,
                'ApplicantCompany': 'DCWater', 'EventTypeDescription': 'Construction Staging Area',
                'MultiAddresses': None, 'WorkLocationFullAddress': '10 TEST STREET NW',
                'ExtraField': 'preserve commas, quotes " and \nnewlines'}, 'geometry': {'x': -77.0, 'y': 38.9}}

    def candidate(self, key='road', distance=1, name='TEST ST NW', kind='Street'):
        return {'subBlockKey': key, 'offsetInMeters': distance, 'routeName': name, 'routeType': kind}

    def road(self, code=3):
        return {'SUBBLOCKKEY': 'road', 'ROADTYPE': '1', 'FHWAFUNCTIONALCLASS': code}

    def test_date_or_and_negative_filters(self):
        attrs = self.feature()['attributes']
        attrs['ApplicationDate'] = app.START - 1
        self.assertFalse(app.qualifies(attrs))
        attrs['IssueDate'] = app.START
        self.assertTrue(app.qualifies(attrs))
        attrs['IssueDate'] = app.END
        self.assertFalse(app.qualifies(attrs))
        attrs['ApplicationDate'] = app.END - 1
        self.assertTrue(app.qualifies(attrs))
        attrs['ApplicantCompany'] = 'CONSOLIDATED WATERPROOFING'
        self.assertFalse(app.qualifies(attrs))
        attrs['ApplicantCompany'] = 'DCWater'
        attrs['EventTypeDescription'] = 'Moving Truck'
        self.assertFalse(app.qualifies(attrs))

    def test_alley_exclusion_missing_class_and_lookup(self):
        response = {'pointOnSubBlocks': [self.candidate('alley', 0, kind='Alley'), self.candidate()]}
        result = app.match(self.feature(), response, {'road': self.road()})
        self.assertEqual(result['fhwa_code'], 3)
        self.assertEqual(result['subblock_key'], 'road')
        self.assertEqual(app.match(self.feature(), response, {})['match_reason'], 'missing_subblock_lookup')
        self.assertEqual(app.match(self.feature(), response, {'road': self.road(None)})['fhwa_code'], '')
        self.assertEqual(app.match(self.feature(), {'error': 'HTTP 503'}, {})['match_reason'], 'service_error')

    def test_ambiguity_and_metadata_api_errors(self):
        response = {'pointOnSubBlocks': [self.candidate(), self.candidate('other', 1.5, 'OTHER ST NW')]}
        self.assertEqual(app.match(self.feature(), response, {})['match_reason'], 'ambiguous_different_roads_within_1m')
        with self.assertRaises(ValueError):
            app.validate_metadata({'fields': []}, ['TrackingNumber'])
        with self.assertRaises(ValueError):
            app.validate_response({'error': {'code': 400}})
        with self.assertRaises(ValueError):
            app.match(self.feature(), {}, {})
        with self.assertRaises(ValueError):
            app.checked_path(app.ROOT.parent)

    def test_http_200_status_error_is_not_a_successful_api_response(self):
        payload = {'status': 'error', 'messages': [
            'Could not access any server machines. Please contact your system administrator.']}
        response = Mock()
        response.json.return_value = payload
        session = Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(ValueError, 'Could not access any server machines'):
            app.api(session, app.LRS, x=-77, y=39)
        response.raise_for_status.assert_called_once_with()

        empty = {'Success': True, 'pointOnSubBlocks': []}
        response.json.return_value = empty
        self.assertEqual(app.api(session, app.LRS, x=-77, y=39), empty)

    def test_service_road_response_type_is_eligible_and_alley_stays_excluded(self):
        response = {'pointOnSubBlocks': [self.candidate('alley', 0, kind='Alley'),
                                        self.candidate('road', 0.5, kind='Service Road'),
                                        self.candidate('street', 3)]}
        road = {**self.road(5), 'ROADTYPE': '2'}
        result = app.match(self.feature(), response, {'road': road})
        self.assertEqual((result['match_status'], result['subblock_key'], result['fhwa_code']),
                         ('matched', 'road', 5))
        self.assertEqual(result['candidate_count'], 2)

    def test_offline_all_columns_hierarchy_and_independent_verifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root/'snapshot'
            snapshot.mkdir()
            features = [self.feature(location=1), self.feature(location=2), self.feature(location=3),
                        self.feature(tracking=2, location=4)]
            for i, feature in enumerate(features):
                feature['geometry']['x'] += i/1000
            names = list(features[0]['attributes'])
            metadata = {'fields': [{'name': name} for name in names]}
            control = self.feature(tracking=99, location=99)
            control['attributes']['ApplicantCompany'] = 'Other'
            app.save(snapshot/'permits.json', {'metadata': metadata, 'features': features,
                     'controls': [{'reason': 'utility', 'feature': control}]})
            responses = {app.point_key(f): {'pointOnSubBlocks': [self.candidate('road'+str(i))]}
                         for i, f in enumerate(features)}
            responses[app.point_key(features[3])]['pointOnSubBlocks'].append(
                self.candidate('crossroad', 1.5, 'CROSS ST NW'))
            app.save(snapshot/'lrs.json', responses)
            road_features = [{'attributes': {**self.road(code), 'SUBBLOCKKEY': 'road'+str(i)}}
                             for i, code in enumerate([7, 3, None, 7])]
            app.save(snapshot/'roads.json', {'metadata': {'fields': [{'name': x} for x in self.road()]},
                                            'features': road_features})
            app.save(snapshot/'manifest.json', {'selected_applications': [1, 2],
                     'whole_application_object_ids': {'1': [1, 2, 3], '2': [4]},
                     'hashes': {name: app.digest(snapshot/name) for name in ['permits.json', 'lrs.json', 'roads.json']}})
            output = root/'output'
            app.run(snapshot, output)
            app.verify(snapshot, output)
            with (output/'permits_enriched.csv').open(newline='', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]['ExtraField'], features[0]['attributes']['ExtraField'])
            self.assertEqual({r['enrich_highest_known_code'] for r in rows[:3]}, {'3'})
            self.assertEqual({r['enrich_application_complete'] for r in rows}, {'False'})
            self.assertEqual({r['enrich_application_highest_code'] for r in rows}, {''})
            self.assertEqual(rows[0]['PermitNumber'], '')
            self.assertEqual(rows[3]['enrich_match_reason'], 'ambiguous_different_roads_within_1m')
            original_rows = [dict(row) for row in rows]
            original_manifest = app.load(output/'manifest.json')
            for row in rows:
                row.update(enrich_match_status='unresolved', enrich_match_reason='reviewer_invented_reason',
                           enrich_fhwa_code='', enrich_fhwa_name='', enrich_highest_known_code='',
                           enrich_highest_known_name='', enrich_matched_locations='0',
                           enrich_application_complete='False')
            with (output/'permits_enriched.csv').open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            app.save(output/'manifest.json', {**original_manifest,
                     'csv_sha256': app.digest(output/'permits_enriched.csv'),
                     'match_counts': {'unresolved': len(rows)},
                     'exception_counts': {'reviewer_invented_reason': len(rows)}})
            with self.assertRaisesRegex(ValueError, 'Source-derived match mismatch'):
                app.verify(snapshot, output)
            rows = original_rows
            # Corrupt an original value and refresh output hash to test semantic verification.
            rows[0]['ExtraField'] = 'corrupted'
            with (output/'permits_enriched.csv').open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            manifest = original_manifest
            manifest['csv_sha256'] = app.digest(output/'permits_enriched.csv')
            app.save(output/'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'Source value changed'):
                app.verify(snapshot, output)
            # A missing source field must not become a silently blank CSV cell.
            source = app.load(snapshot/'permits.json')
            del source['features'][0]['attributes']['ExtraField']
            app.save(snapshot/'permits.json', source)
            manifest = app.load(snapshot/'manifest.json')
            manifest['hashes']['permits.json'] = app.digest(snapshot/'permits.json')
            app.save(snapshot/'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'Source fields missing'):
                app.inputs(snapshot)

    def test_collision_safe_prefix(self):
        # The real schema is checked before enrichment columns are selected.
        names = ['OBJECTID', 'enrich_utility', 'enrich__utility']
        prefix = 'enrich_'
        while any(name.startswith(prefix) for name in names):
            prefix += '_'
        self.assertEqual(prefix, 'enrich___')

    def test_reviewed_cases_keep_conservative_negative_controls(self):
        snapshot = app.ROOT/'snapshots/pilot_20261014'
        _, source, responses, roads, _, _ = app.inputs(snapshot)
        features = [f for f in source['features'] if f['attributes']['OBJECTID'] in {1007738, 1015354}]
        self.assertEqual(len(features), 2)
        for feature in features:
            response = responses[app.point_key(feature)]
            result = app.match(feature, response, roads)
            self.assertEqual((result['subblock_key'], result['fhwa_code'], result['road_type']),
                             (app.RESOLUTIONS['subblock_key'], 3, '1'))
            self.assertEqual(result['resolution_id'], 'python_oid_' + str(feature['attributes']['OBJECTID']))
            self.assertEqual(result['match_reason'], app.RESOLUTIONS['policy'])
            self.assertEqual(app.match(feature, response, roads, False)['match_reason'], app.ADDRESS_REASON)
            for field, value in [('OBJECTID', 999), ('TrackingNumber', 999), ('LocationID', 999)]:
                changed = copy.deepcopy(feature)
                changed['attributes'][field] = value
                result = app.match(changed, response, roads)
                self.assertEqual(result['match_reason'], app.ADDRESS_REASON)
                self.assertTrue(result['resolution_id'].startswith(app.MATCH_POLICY))
            changed = copy.deepcopy(feature)
            changed['attributes']['WorkLocationFullAddress'] = 'OTHER BLOCK OF BENNING ROAD NE'
            self.assertEqual(app.match(changed, response, roads)['match_status'], 'unresolved')
            moved = copy.deepcopy(feature)
            moved['geometry']['x'] += 0.00001
            self.assertEqual(app.match(moved, response, roads)['match_reason'], app.ADDRESS_REASON)
            multiple = copy.deepcopy(response)
            multiple['pointOnSubBlocks'][1]['unitBlock'] = app.RESOLUTIONS['address']
            self.assertEqual(app.match(feature, multiple, roads)['match_status'], 'unresolved')
            for field, value in [('ROADTYPE', '3'), ('SUBBLOCKKEY', 'wrong'), ('ROUTENAME', 'OTHER'),
                                 ('FHWAFUNCTIONALCLASS', True), ('FHWAFUNCTIONALCLASS', None)]:
                changed_roads = copy.deepcopy(roads)
                changed_roads[app.RESOLUTIONS['subblock_key']][field] = value
                self.assertEqual(app.match(feature, response, changed_roads)['match_status'], 'unresolved')
            excluded = copy.deepcopy(response)
            excluded['pointOnSubBlocks'][0]['routeType'] = 'Alley'
            self.assertNotEqual(app.match(feature, excluded, roads)['fhwa_code'], 3)
            self.assertTrue(all(not app.qualifies(c['feature']['attributes']) for c in source['controls']))

    def test_general_exact_street_rule_does_not_choose_highest_class(self):
        feature = self.feature()
        feature['attributes']['WorkLocationFullAddress'] = '100 BLOCK OF TEST STREET NW'
        nearest = {**self.candidate(), 'unitBlock': feature['attributes']['WorkLocationFullAddress']}
        ramp = self.candidate('ramp', 1.5, 'RAMP', 'Ramp')
        roads = {'road': {**self.road(7), 'ROUTENAME': 'TEST ST NW'},
                 'ramp': {'SUBBLOCKKEY': 'ramp', 'ROADTYPE': '3', 'FHWAFUNCTIONALCLASS': 2}}
        response = {'pointOnSubBlocks': [nearest, ramp]}
        result = app.match(feature, response, roads)
        self.assertEqual((result['fhwa_code'], result['match_reason']), (7, app.ADDRESS_REASON))
        ramp['unitBlock'] = nearest['unitBlock']
        self.assertEqual(app.match(feature, response, roads)['match_reason'], 'multiple_exact_unit_blocks')
        ramp['routeName'] = nearest['routeName']
        self.assertEqual(app.match(feature, response, roads)['fhwa_code'], 7)
        ramp['routeName'] = 'RAMP'
        del ramp['unitBlock']
        nearest['offsetInMeters'] = 2
        self.assertEqual(app.match(feature, response, roads)['match_status'], 'unresolved')

    def test_frozen_resolutions_independent_verifier_and_separate_applications(self):
        snapshot = app.ROOT/'snapshots/pilot_20261014'
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'output'
            app.run(snapshot, output)
            with patch.object(app, 'match', side_effect=AssertionError('Verifier called producer')):
                app.verify(snapshot, output)
            with (output/'permits_enriched.csv').open(newline='', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            for tracking, count in [('11207147', 3), ('11213896', 4)]:
                group = [r for r in rows if r['TrackingNumber'] == tracking]
                self.assertEqual(len(group), count)
                self.assertEqual({r['enrich_highest_known_code'] for r in group}, {'3'})
                self.assertEqual({r['enrich_application_complete'] for r in group}, {'True'})
                self.assertEqual({r['enrich_application_highest_code'] for r in group}, {'3'})
                self.assertEqual({r['enrich_matched_locations'] for r in group}, {str(count)})
            self.assertEqual(len(rows), 47)
            self.assertEqual(sum(bool(r['enrich_resolution_id']) for r in rows), 2)
            self.assertNotIn('969742', {r['OBJECTID'] for r in rows})
            self.assertNotIn('964512', {r['OBJECTID'] for r in rows})
            self.assertNotIn('932906', {r['OBJECTID'] for r in rows})
            original = app.load(app.ROOT/'runs/20261014T213655293397Z/manifest.json')
            self.assertEqual(app.load(output/'manifest.json')['snapshot_manifest_sha256'],
                             original['snapshot_manifest_sha256'])
            # Rehashing a fabricated case provenance must not evade source-derived verification.
            next(r for r in rows if r['OBJECTID'] == '1007738')['enrich_resolution_id'] = 'fabricated'
            with (output/'permits_enriched.csv').open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            report = app.load(output/'manifest.json')
            report['csv_sha256'] = app.digest(output/'permits_enriched.csv')
            app.save(output/'manifest.json', report)
            with self.assertRaisesRegex(ValueError, 'Source-derived match mismatch: resolution_id'):
                app.verify(snapshot, output)

    def test_new_snapshot_uses_general_policy_with_independent_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary)/'snapshot'
            shutil.copytree(app.ROOT/'snapshots/pilot_20261014', snapshot)
            manifest = app.load(snapshot/'manifest.json')
            manifest['test_new_snapshot'] = True
            app.save(snapshot/'manifest.json', manifest)
            output = Path(temporary)/'output'
            app.run(snapshot, output)
            with patch.object(app, 'match', side_effect=AssertionError('Verifier called producer')):
                app.verify(snapshot, output)
            with (output/'permits_enriched.csv').open(newline='', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            resolved = [r for r in rows if r['enrich_match_reason'] == app.ADDRESS_REASON]
            self.assertEqual({r['OBJECTID'] for r in resolved}, {'1007738', '1015354'})
            self.assertTrue(all(r['enrich_resolution_id'].startswith(app.MATCH_POLICY) for r in resolved))
            extra = self.feature(tracking=11207147, location=9999999)
            extra['attributes']['EventTypeDescription'] = 'Moving Truck'
            app.save(snapshot/'application_context.json', {'features': [extra]})
            audit = {tracking: {'eligible_object_ids': ids,
                               'complete_object_ids': sorted(ids + ([9999999] if tracking == '11207147' else [])),
                               'filtered_group_complete': tracking != '11207147'}
                     for tracking, ids in manifest['whole_application_object_ids'].items()}
            manifest['application_group_audit'] = audit
            manifest['hashes']['application_context.json'] = app.digest(snapshot/'application_context.json')
            app.save(snapshot/'manifest.json', manifest)
            output = Path(temporary)/'context_output'
            app.run(snapshot, output)
            app.verify(snapshot, output)
            with (output/'permits_enriched.csv').open(newline='', encoding='utf-8') as stream:
                affected = [r for r in csv.DictReader(stream) if r['TrackingNumber'] == '11207147']
            self.assertEqual({r['enrich_application_highest_code'] for r in affected}, {''})
            self.assertEqual({r['enrich_highest_known_code'] for r in affected}, {'3'})
            audit['11207147']['filtered_group_complete'] = True
            app.save(snapshot/'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'Application context membership mismatch'):
                app.inputs(snapshot)

    def test_typed_fallback_requires_complete_raw_responses_and_exact_aggregate(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary)/'snapshot'
            shutil.copytree(app.ROOT/'snapshots/pilot_20261014', snapshot)
            manifest = app.load(snapshot/'manifest.json')
            lrs = app.load(snapshot/'lrs.json')
            key = next(iter(lrs))
            typed = {kind: {'pointOnSubBlocks': [self.candidate(kind, kind=kind)]}
                     for kind in ('Street', 'Service', 'Ramp')}
            typed['Service']['pointOnSubBlocks'][0]['routeType'] = 'Service Road'
            success = {'lookup_method': 'explicit_eligible_route_types_v1',
                       'original_all_error': {'error': 'API 500'}, 'typed_responses': typed,
                       'pointOnSubBlocks': [p for raw in typed.values() for p in raw['pointOnSubBlocks']]}

            def write_response(response):
                lrs[key] = response
                app.save(snapshot/'lrs.json', lrs)
                manifest['hashes']['lrs.json'] = app.digest(snapshot/'lrs.json')
                app.save(snapshot/'manifest.json', manifest)

            write_response(success)
            app.inputs(snapshot)
            malformed = []
            missing = copy.deepcopy(success)
            del missing['typed_responses']['Ramp']
            malformed.append(missing)
            for raw in ({'error': {'code': 500}}, {'Success': False, 'pointOnSubBlocks': []},
                        {'pointOnSubBlocks': None}, {'pointOnSubBlocks': [self.candidate(kind='Alley')]}):
                changed = copy.deepcopy(success)
                changed['typed_responses']['Ramp'] = raw
                malformed.append(changed)
            changed = copy.deepcopy(success)
            changed['pointOnSubBlocks'].reverse()
            malformed.append(changed)
            for response in malformed:
                write_response(response)
                with self.assertRaisesRegex(ValueError, 'typed LRS|Typed LRS'):
                    app.inputs(snapshot)
            failure = {'lookup_method': success['lookup_method'], 'typed_responses': {'Street': typed['Street']},
                       'error': 'Ramp unavailable', 'unavailable': True}
            write_response(failure)
            app.inputs(snapshot)
            self.assertEqual(app.match(self.feature(), failure, {})['match_reason'], 'service_error')
            self.assertEqual(app.match(self.feature(), {'unavailable': True}, {})['match_reason'], 'service_error')


if __name__ == '__main__':
    unittest.main()
