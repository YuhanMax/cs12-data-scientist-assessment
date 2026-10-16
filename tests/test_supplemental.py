"""Offline evidence gates for conservative v5 supplemental matches."""
import copy
import json
import unittest

from scripts import enrich_permits as e
from scripts import supplemental as s


class SupplementalTests(unittest.TestCase):
    def feature(self, address='10 A STREET NW'):
        return {'attributes': {'WorkLocationFullAddress': address}, 'geometry': {'x': -77, 'y': 39}}

    def candidate(self, key, name, distance, kind='Street'):
        return {'subBlockKey': key, 'routeName': name, 'routeType': kind,
                'offsetInMeters': distance, 'unitBlock': '0 - 99 BLOCK OF ' + name}

    def road(self, key, name, code=7, roadtype='1'):
        return {'SUBBLOCKKEY': key, 'ROUTENAME': name, 'ROADTYPE': roadtype,
                'FHWAFUNCTIONALCLASS': code}

    def baseline(self, reason='ambiguous_different_roads_within_1m'):
        return {'match_status': 'unresolved', 'match_reason': reason,
                'subblock_key': 'old-diagnostic', 'road_name': 'old-road',
                'road_type': '', 'distance_m': 0.2, 'candidate_count': 2,
                'fhwa_code': '', 'fhwa_name': '', 'resolution_id': 'old',
                'resolution_basis': 'old'}

    def intersection_inputs(self):
        feature = self.feature('A STREET NW AND B STREET NW')
        candidates = [self.candidate('b', 'B ST NW', 0.8),
                      self.candidate('a', 'A ST NW', 0.2)]
        roads = {'a': self.road('a', 'A ST NW'), 'b': self.road('b', 'B ST NW')}
        return feature, {'pointOnSubBlocks': candidates}, roads

    def mar_evidence(self, key='address-road', address='10 A STREET NW', status='ACTIVE'):
        return {'source_url': 'https://example.test/mar', 'road_source_url': e.ROADS,
                'base_snapshot_sha256': 'frozen-hash', 'queries': [],
                'address_features': [{'attributes': {'ADDRESS': address, 'STATUS': status,
                                                     'SUBBLOCKKEY': key}}],
                'road_features': [{'attributes': self.road(key, 'A ST NW', 4)}]}

    def mar_inputs(self):
        feature = self.feature()
        response = {'pointOnSubBlocks': [self.candidate('nearest', 'B ST NW', 0.2),
                                         self.candidate('address-road', 'A ST NW', 30.0)]}
        roads = {'nearest': self.road('nearest', 'B ST NW', 7),
                 'address-road': self.road('address-road', 'A ST NW', 4)}
        return feature, response, roads, self.mar_evidence()

    def test_intersection_consensus_reports_class_without_inventing_road(self):
        feature, response, roads = self.intersection_inputs()
        baseline = self.baseline()
        before = copy.deepcopy((feature, response, roads, baseline))
        result = s.apply(feature, response, roads, baseline, None)
        self.assertEqual(result['match_status'], 'matched')
        self.assertEqual(result['match_reason'], 'intersection_class_consensus')
        self.assertEqual((result['fhwa_code'], result['fhwa_name']), (7, e.LABELS[7]))
        self.assertEqual(result['class_method'], 'intersection_consensus')
        self.assertEqual(result['supporting_subblock_keys'], json.dumps(['a', 'b']))
        self.assertEqual(result['evidence_reference'], 'frozen_lrs_and_roads')
        self.assertEqual(result['resolution_basis'], s.INTERSECTION_BASIS)
        self.assertEqual({result[k] for k in ('subblock_key', 'road_name', 'road_type',
                                              'distance_m', 'resolution_id')}, {''})
        self.assertEqual((feature, response, roads, baseline), before)
        self.assertIsNot(result, baseline)

    def test_intersection_rejects_mixed_class_missing_arm_and_nonstandard_names(self):
        feature, response, roads = self.intersection_inputs()
        baseline = self.baseline()
        roads['b']['FHWAFUNCTIONALCLASS'] = 3
        self.assertEqual(s.apply(feature, response, roads, baseline, None), baseline)
        roads['b']['FHWAFUNCTIONALCLASS'] = 7
        for address in ('A STREET NW AND C STREET NW',
                        'A STREET NW AND B STREET',
                        'A STREET NW AND RAMP FROM B STREET NW',
                        'A STREET NW AND NORTH CAPITOL STREET',
                        'A STREET NW AND B STREET NW AND C STREET NW'):
            with self.subTest(address=address):
                self.assertEqual(s.apply(self.feature(address), response, roads, baseline, None), baseline)
        del roads['b']
        self.assertEqual(s.apply(feature, response, roads, baseline, None), baseline)

    def test_intersection_requires_every_tied_road_identity_type_and_class(self):
        feature, response, roads = self.intersection_inputs()
        baseline = self.baseline()
        for field, value in [('ROUTENAME', 'WRONG ST NW'), ('ROADTYPE', '3'),
                             ('FHWAFUNCTIONALCLASS', None)]:
            changed = copy.deepcopy(roads)
            changed['b'][field] = value
            with self.subTest(field=field):
                self.assertEqual(s.apply(feature, response, changed, baseline, None), baseline)
        response['pointOnSubBlocks'].append(self.candidate('c', 'C ST NW', 0.9))
        roads['c'] = self.road('c', 'C ST NW', 3)
        self.assertEqual(s.apply(feature, response, roads, baseline, None), baseline)
        roads['c'] = self.road('c', 'C ST NW', 7, '3')
        response['pointOnSubBlocks'][-1] = self.candidate('c', 'Ramp-123', 0.9, 'Ramp')
        roads['c']['ROUTENAME'] = 'Ramp-123'
        self.assertEqual(s.apply(feature, response, roads, baseline, None), baseline)

    def test_mar_exact_active_address_can_choose_farther_frozen_candidate(self):
        feature, response, roads, evidence = self.mar_inputs()
        baseline = self.baseline('named_street_disagreement')
        before = copy.deepcopy((feature, response, roads, baseline, evidence))
        result = s.apply(feature, response, roads, baseline, evidence)
        self.assertEqual(result['match_reason'], 'mar_exact_address')
        self.assertEqual(result['match_status'], 'matched')
        self.assertEqual((result['subblock_key'], result['road_name'], result['distance_m']),
                         ('address-road', 'A ST NW', 30.0))
        self.assertEqual((result['fhwa_code'], result['class_method']), (4, 'mar_address'))
        self.assertEqual(result['supporting_subblock_keys'], json.dumps(['address-road']))
        self.assertEqual(result['evidence_reference'], 'mar_evidence.json')
        self.assertEqual(result['resolution_basis'], s.MAR_BASIS)
        self.assertEqual((feature, response, roads, baseline, evidence), before)

    def test_mar_rejects_conflicting_blank_or_missing_status_active_rows(self):
        feature, response, roads, evidence = self.mar_inputs()
        baseline = self.baseline('named_street_disagreement')
        for key in ('different-key', ''):
            changed = copy.deepcopy(evidence)
            changed['address_features'].append({'attributes': {'ADDRESS': '10 A STREET NW',
                                                               'STATUS': 'ACTIVE', 'SUBBLOCKKEY': key}})
            with self.subTest(key=key):
                self.assertEqual(s.apply(feature, response, roads, baseline, changed), baseline)
        changed = copy.deepcopy(evidence)
        del changed['address_features'][0]['attributes']['STATUS']
        self.assertEqual(s.apply(feature, response, roads, baseline, changed), baseline)
        changed = copy.deepcopy(evidence)
        changed['address_features'].append({'attributes': {'ADDRESS': '10 A STREET NW',
                                                           'SUBBLOCKKEY': 'address-road'}})
        self.assertEqual(s.apply(feature, response, roads, baseline, changed), baseline)

    def test_mar_rejects_stale_road_or_candidate_outside_frozen_50m(self):
        feature, response, roads, evidence = self.mar_inputs()
        baseline = self.baseline('named_street_disagreement')
        changed = copy.deepcopy(evidence)
        changed['road_features'][0]['attributes']['FHWAFUNCTIONALCLASS'] = 3
        self.assertEqual(s.apply(feature, response, roads, baseline, changed), baseline)
        one_class_roads = copy.deepcopy(roads)
        one_class_roads['address-road']['FHWAFUNCTIONALCLASS'] = 1
        changed = copy.deepcopy(evidence)
        changed['road_features'][0]['attributes']['FHWAFUNCTIONALCLASS'] = True
        self.assertEqual(s.apply(feature, response, one_class_roads, baseline, changed), baseline)
        changed = copy.deepcopy(response)
        changed['pointOnSubBlocks'][1]['offsetInMeters'] = 50.01
        self.assertEqual(s.apply(feature, changed, roads, baseline, evidence), baseline)
        changed = copy.deepcopy(roads)
        changed['address-road']['ROUTENAME'] = 'C ST NW'
        self.assertEqual(s.apply(feature, response, changed, baseline, evidence), baseline)

    def test_matched_missing_geometry_or_service_error_never_overridden(self):
        feature, response, roads, evidence = self.mar_inputs()
        matched = {**self.baseline(), 'match_status': 'matched', 'match_reason': 'nearest_eligible_road',
                   'fhwa_code': 7}
        result = s.apply(feature, response, roads, matched, evidence)
        self.assertEqual(result, matched)
        self.assertIsNot(result, matched)
        for reason in ('service_error', 'missing_geometry'):
            baseline = self.baseline(reason)
            self.assertEqual(s.apply(feature, response, roads, baseline, evidence), baseline)
        feature['geometry'] = None
        self.assertEqual(s.apply(feature, response, roads, self.baseline(), evidence), self.baseline())


if __name__ == '__main__':
    unittest.main()
