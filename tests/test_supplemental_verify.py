"""Adversarial checks for independent v5 evidence derivation."""

import json
import unittest

from scripts.supplemental_verify import apply_expected


def road(key, name, code=7, kind='1'):
    return {'SUBBLOCKKEY': key, 'ROUTENAME': name, 'ROADTYPE': kind,
            'FHWAFUNCTIONALCLASS': code}


def candidate(key, name, distance, kind='Street'):
    return {'subBlockKey': key, 'routeName': name, 'routeType': kind,
            'offsetInMeters': distance}


class SupplementalVerifyTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {'match_status': 'unresolved', 'match_reason': 'ambiguous_different_roads_within_1m',
                         'candidate_count': 2, 'subblock_key': 'diagnostic', 'road_name': 'OTHER ST NE',
                         'road_type': '', 'distance_m': 0.5, 'fhwa_code': '', 'fhwa_name': '',
                         'resolution_id': '', 'resolution_basis': '', 'class_method': '',
                         'supporting_subblock_keys': '[]', 'evidence_reference': ''}

    def feature(self, address):
        return {'geometry': {'x': -77, 'y': 38.9},
                'attributes': {'WorkLocationFullAddress': address}}

    def apply(self, address, candidates, roads, evidence=None, baseline=None):
        return apply_expected(self.feature(address), {'pointOnSubBlocks': candidates}, roads,
                              baseline or self.baseline, evidence or {})

    def test_intersection_requires_both_arms_and_same_verified_class(self):
        address = 'HOLBROOK STREET NE AND MORSE STREET NE'
        rows = [candidate('z', 'HOLBROOK ST NE', 0.5), candidate('a', 'MORSE ST NE', 1.2)]
        roads = {'z': road('z', 'HOLBROOK ST NE'), 'a': road('a', 'MORSE ST NE')}
        result = self.apply(address, rows, roads)
        self.assertEqual((result['match_status'], result['match_reason'], result['fhwa_code']),
                         ('matched', 'intersection_class_consensus', 7))
        self.assertEqual(result['supporting_subblock_keys'], '["a", "z"]')
        self.assertEqual((result['subblock_key'], result['road_name'], result['road_type'],
                          result['distance_m'], result['resolution_id']), ('', '', '', '', ''))
        self.assertEqual(result['class_method'], 'intersection_consensus')
        self.assertEqual(result['evidence_reference'], 'frozen_lrs_and_roads')
        for altered in (rows[:1], [rows[0], {**rows[1], 'offsetInMeters': 1.6}]):
            self.assertEqual(self.apply(address, altered, roads), self.baseline)
        self.assertEqual(self.apply(address, rows, {**roads, 'a': road('a', 'MORSE ST NE', 4)}),
                         self.baseline)

    def test_intersection_rejects_unverified_tie_even_with_consensus_on_other_roads(self):
        rows = [candidate('a', 'HOLBROOK ST NE', 0.2),
                candidate('b', 'MORSE ST NE', 0.3), candidate('c', 'MORSE ST NE', 0.4)]
        roads = {'a': road('a', 'HOLBROOK ST NE'), 'b': road('b', 'MORSE ST NE')}
        address = 'HOLBROOK STREET NE AND MORSE STREET NE'
        self.assertEqual(self.apply(address, rows, roads), self.baseline)
        for bad in (road('c', 'WRONG ST NE'), road('c', 'MORSE ST NE', None),
                    road('c', 'MORSE ST NE', 7, '4')):
            self.assertEqual(self.apply(address, rows, {**roads, 'c': bad}), self.baseline)
        renamed = {**roads, 'c': road('c', 'MORSE STREET NE')}
        self.assertEqual(self.apply(address, rows, renamed), self.baseline)

    def test_intersection_special_description_is_not_promoted(self):
        rows = [candidate('a', 'HOLBROOK ST NE', 0.2), candidate('b', 'MORSE ST NE', 0.3)]
        roads = {'a': road('a', 'HOLBROOK ST NE'), 'b': road('b', 'MORSE ST NE')}
        for address in ('HOLBROOK STREET BN AND MORSE STREET NE',
                        'HOLBROOK STREET NE AND RAMP NE',
                        'HOLBROOK STREET NE AND MORSE STREET'):
            self.assertEqual(self.apply(address, rows, roads), self.baseline)

    def mar_evidence(self, key='target', code=4):
        return {'address_features': [{'attributes': {'ADDRESS': '1703 MINNESOTA AVENUE SE',
                                                     'STATUS': 'ACTIVE', 'SUBBLOCKKEY': key,
                                                     'MAR_ID': 1, 'OBJECTID': 2,
                                                     'ROUTEID': 'route'}}],
                'road_features': [{'attributes': road(key, 'MINNESOTA AVE SE', code)}]}

    def test_mar_requires_exact_active_unique_key_and_frozen_current_agreement(self):
        address = '1703 MINNESOTA AVENUE SE'
        rows = [candidate('wrong', 'S ST SE', 0.2),
                candidate('target', 'MINNESOTA AVE SE', 35)]
        roads = {'wrong': road('wrong', 'S ST SE', 7),
                 'target': road('target', 'MINNESOTA AVE SE', 4)}
        evidence = self.mar_evidence()
        result = self.apply(address, rows, roads, evidence)
        self.assertEqual((result['match_status'], result['match_reason'], result['fhwa_code']),
                         ('matched', 'mar_exact_address', 4))
        self.assertEqual((result['subblock_key'], result['road_name'], result['distance_m']),
                         ('target', 'MINNESOTA AVE SE', 35))
        self.assertEqual(result['supporting_subblock_keys'], '["target"]')
        self.assertEqual((result['class_method'], result['evidence_reference']),
                         ('mar_address', 'mar_evidence.json'))
        self.assertEqual(self.apply(address, rows, roads, self.mar_evidence(code=3)), self.baseline)
        self.assertEqual(self.apply(address, rows, roads, self.mar_evidence(key='absent')), self.baseline)
        self.assertEqual(self.apply(address, [rows[0], {**rows[1], 'offsetInMeters': 51}],
                                    roads, evidence), self.baseline)
        self.assertEqual(self.apply(address, rows, {**roads, 'target': road('target', 'S ST SE', 4)},
                                    evidence), self.baseline)

    def test_mar_rejects_conflicting_active_rows_and_duplicate_road_rows(self):
        address = '1703 MINNESOTA AVENUE SE'
        rows = [candidate('target', 'MINNESOTA AVE SE', 2)]
        roads = {'target': road('target', 'MINNESOTA AVE SE', 4)}
        evidence = self.mar_evidence()
        conflicting = json.loads(json.dumps(evidence))
        conflicting['address_features'].append({'attributes': {**conflicting['address_features'][0]['attributes'],
                                                               'SUBBLOCKKEY': 'different'}})
        self.assertEqual(self.apply(address, rows, roads, conflicting), self.baseline)
        duplicate = json.loads(json.dumps(evidence))
        duplicate['road_features'].append(duplicate['road_features'][0])
        self.assertEqual(self.apply(address, rows, roads, duplicate), self.baseline)
        inactive = json.loads(json.dumps(evidence))
        inactive['address_features'][0]['attributes']['STATUS'] = 'INACTIVE'
        self.assertEqual(self.apply(address, rows, roads, inactive), self.baseline)

    def test_matched_missing_geometry_and_service_error_never_change(self):
        address = '1703 MINNESOTA AVENUE SE'
        rows = [candidate('target', 'MINNESOTA AVE SE', 2)]
        roads = {'target': road('target', 'MINNESOTA AVE SE', 4)}
        evidence = self.mar_evidence()
        matched = dict(self.baseline, match_status='matched', fhwa_code=7)
        self.assertEqual(self.apply(address, rows, roads, evidence, matched), matched)
        feature = self.feature(address)
        feature['geometry'] = None
        self.assertEqual(apply_expected(feature, {'pointOnSubBlocks': rows}, roads,
                                        self.baseline, evidence), self.baseline)
        for response in ({'error': 'down', 'pointOnSubBlocks': rows},
                         {'status': 'error', 'pointOnSubBlocks': rows},
                         {'Success': False, 'pointOnSubBlocks': rows}):
            self.assertEqual(apply_expected(self.feature(address), response, roads,
                                            self.baseline, evidence), self.baseline)
        service_baseline = dict(self.baseline, match_reason='service_error')
        self.assertEqual(self.apply(address, rows, roads, evidence, service_baseline),
                         service_baseline)


if __name__ == '__main__':
    unittest.main()
