import unittest

from scripts import enrich_permits as app


class AddressConflictTests(unittest.TestCase):
    def outcome(self, address, block, kind='Street', alternate=False):
        feature = {'attributes': {'OBJECTID': 1, 'WorkLocationFullAddress': address},
                   'geometry': {'x': -77, 'y': 39}}
        nearest = {'subBlockKey': 'near', 'offsetInMeters': 2, 'routeName': 'near',
                   'routeType': kind, 'unitBlock': block}
        candidates = [nearest]
        if alternate:
            candidates.append({**nearest, 'subBlockKey': 'far', 'offsetInMeters': 10,
                               'routeName': 'far', 'unitBlock': '1700 BLOCK OF MINNESOTA AVENUE SE'})
        road = {'SUBBLOCKKEY': 'near', 'ROUTENAME': 'near', 'ROADTYPE': '1',
                'FHWAFUNCTIONALCLASS': 7}
        return app.match(feature, {'pointOnSubBlocks': candidates}, {'near': road})

    def test_known_numbered_street_conflicts_with_or_without_alternative(self):
        for address, block in [('1703 MINNESOTA AVENUE SE', '1700 - 1799 BLOCK OF S STREET SE'),
                               ('1711 35TH STREET NW', '3400 - 3499 BLOCK OF R STREET NW'),
                               ('2009 37TH STREET NW', '3600 - 3699 BLOCK OF U STREET NW')]:
            for alternate in (False, True):
                with self.subTest(address=address, alternate=alternate):
                    result = self.outcome(address, block, alternate=alternate)
                    self.assertEqual(result['match_reason'], 'named_street_disagreement')
                    self.assertEqual(result['fhwa_code'], '')
                    self.assertEqual(result['subblock_key'], 'near')

    def test_same_street_abbreviations_and_service_road(self):
        for kind in ('Street', 'Service Road'):
            result = self.outcome('1703 Minnesota Ave. S.E.',
                                  '1700 - 1799 BLOCK OF MINNESOTA AVENUE SE', kind)
            self.assertEqual(result['match_status'], 'matched')

    def test_same_name_service_road_without_unit_block(self):
        feature = {'attributes': {'OBJECTID': 1, 'WorkLocationFullAddress': '1703 MINNESOTA AVENUE SE'},
                   'geometry': {'x': -77, 'y': 39}}
        candidate = {'subBlockKey': 'service', 'offsetInMeters': 1,
                     'routeName': 'MINNESOTA AVE SE', 'routeType': 'Service Road', 'unitBlock': None}
        road = {'SUBBLOCKKEY': 'service', 'ROUTENAME': 'MINNESOTA AVE SE',
                'ROADTYPE': '2', 'FHWAFUNCTIONALCLASS': 4}
        result = app.match(feature, {'pointOnSubBlocks': [candidate]}, {'service': road})
        self.assertEqual((result['match_status'], result['fhwa_code']), ('matched', 4))

    def test_nonstandard_addresses_or_blocks_are_not_inferred(self):
        for address, block in [('KEY BRIDGE', '1700 BLOCK OF M STREET NW'),
                               ('1703 MINNESOTA AVE SE', 'BRIDGE'),
                               ('1703 MINNESOTA AVE SE / S ST SE', '1700 BLOCK OF S STREET SE')]:
            self.assertEqual(self.outcome(address, block)['match_status'], 'matched')

    def test_existing_range_rule_stays_exact(self):
        self.assertEqual(self.outcome('1700 BLOCK OF MINNESOTA AVE SE',
                                     '1700 BLOCK OF MINNESOTA AVENUE SE')['match_reason'],
                         'unit_block_disagreement')

    def test_explicit_failure_is_not_accepted_even_with_candidates(self):
        feature = {'attributes': {}, 'geometry': {'x': -77, 'y': 39}}
        self.assertEqual(app.match(feature, {'Success': False, 'pointOnSubBlocks': [{}]}, {})
                         ['match_reason'], 'service_error')


if __name__ == '__main__':
    unittest.main()
