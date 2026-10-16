"""Small offline checks for full acquisition and checkpoint safety."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import fetch_full as f


class AcquisitionTests(unittest.TestCase):
    def test_context_retains_filtered_locations_without_expanding_output(self):
        eligible = {'attributes': {'OBJECTID': 1, 'TrackingNumber': 10}}
        extra = {'attributes': {'OBJECTID': 2, 'TrackingNumber': 10}, 'geometry': {'x': 3, 'y': 4}}
        with patch.object(f.e, 'query', side_effect=[{'count': 2}, {'objectIds': [1, 2]},
                                                   {'objectIds': [2, 1]}]), \
                patch.object(f, 'complete_rows', return_value=[extra]):
            context = f.application_context(None, [eligible])
        self.assertEqual(context['features'], [extra])
        self.assertEqual(context['groups']['10'], {'eligible_object_ids': [1],
                         'complete_object_ids': [1, 2], 'filtered_group_complete': False})

    def test_context_rejects_changed_group_membership(self):
        eligible = {'attributes': {'OBJECTID': 1, 'TrackingNumber': 10}}
        with patch.object(f.e, 'query', side_effect=[{'count': 1}, {'objectIds': [1]},
                                                   {'objectIds': [1, 2]}]):
            with self.assertRaisesRegex(ValueError, 'group membership changed'):
                f.application_context(None, [eligible])

    def test_count_mismatch_fails_before_fetch(self):
        with patch.object(f.e, 'query', side_effect=[{'count': 2}, {'objectIds': [1]}]):
            with self.assertRaisesRegex(ValueError, 'count/ID'):
                f.complete_rows(None, 'url', 'filter')

    def test_reconciles_batches_and_final_membership(self):
        rows = [{'attributes': {'OBJECTID': 2}}, {'attributes': {'OBJECTID': 1}}]
        responses = [{'count': 2}, {'objectIds': [1, 2]}, {'features': rows},
                     {'objectIds': [2, 1]}]
        with patch.object(f.e, 'query', side_effect=responses):
            self.assertEqual([r['attributes']['OBJECTID'] for r in
                              f.complete_rows(None, 'url', 'filter')], [1, 2])
        responses[-1] = {'objectIds': [1, 3]}
        with patch.object(f.e, 'query', side_effect=responses):
            with self.assertRaisesRegex(ValueError, 'membership changed'):
                f.complete_rows(None, 'url', 'filter')

    def test_resume_deduplicates_and_retries_only_errors(self):
        good = {'geometry': {'x': 1, 'y': 2}}
        retry = {'geometry': {'x': 3, 'y': 4}}
        missing = {'geometry': None}
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            f.atomic_save(snapshot / 'lrs.json', {
                f.e.point_key(good): {'pointOnSubBlocks': []},
                f.e.point_key(retry): {'error': 'timeout', 'retryable': True},
                f.e.point_key(missing): {'error': 'missing', 'retryable': False}})
            saved_error = {'error': 'timeout', 'retryable': True}
            with patch.object(f, 'get_typed_lrs', return_value={'pointOnSubBlocks': []}) as lookup, \
                    patch.object(f, 'get_lrs') as all_lookup:
                result = f.capture_lrs(snapshot, [good, good, retry, missing], resume=True)
            lookup.assert_called_once_with(retry, saved_error)
            all_lookup.assert_not_called()
            self.assertEqual(len(result), 3)
            self.assertEqual(f.e.load(snapshot / 'lrs.json'), result)
            self.assertFalse((snapshot / 'lrs.json.tmp').exists())

    def typed_response(self, route_type):
        return {'Success': True, 'pointOnSubBlocks': [{'routeType': route_type, 'subBlockKey': route_type}]}

    def test_typed_retry_requires_all_three_and_preserves_raw(self):
        feature = {'geometry': {'x': -77, 'y': 39}}
        previous = {'error': 'All HTTP500', 'retryable': True}
        payloads = [self.typed_response(kind) for kind in ('Street', 'Service', 'Ramp')]
        session = Mock()
        session.get.side_effect = [Mock(json=Mock(return_value=payload)) for payload in payloads]
        with patch.object(f.e, 'client') as factory:
            factory.return_value.__enter__.return_value = session
            result = f.get_typed_lrs(feature, previous)
        self.assertNotIn('error', result)
        self.assertEqual(result['original_all_error'], previous)
        self.assertEqual(result['pointOnSubBlocks'], [p for raw in payloads for p in raw['pointOnSubBlocks']])
        self.assertEqual(list(result['typed_responses']), ['Street', 'Service', 'Ramp'])
        self.assertEqual([c.kwargs['params']['routeType'] for c in session.get.call_args_list],
                         ['Street', 'Service', 'Ramp'])
        for call in session.get.call_args_list:
            self.assertEqual(call.kwargs['params']['searchRadius'], 50)
            self.assertEqual(call.kwargs['params']['returnNearestMatchOnly'], 'false')

    def test_typed_partial_error_never_exposes_candidates(self):
        payloads = [self.typed_response('Street'), {'error': {'code': 500}}, self.typed_response('Ramp')]
        session = Mock()
        session.get.side_effect = [Mock(json=Mock(return_value=payload)) for payload in payloads]
        with patch.object(f.e, 'client') as factory:
            factory.return_value.__enter__.return_value = session
            result = f.get_typed_lrs({'geometry': {'x': 1, 'y': 2}}, {'error': 'All failed'})
        self.assertTrue(result['unavailable'])
        self.assertNotIn('pointOnSubBlocks', result)
        self.assertEqual(result['typed_responses']['Service'], payloads[1])

    def test_service_road_raw_label_is_valid_but_other_types_fail(self):
        for returned_type, succeeds in [('Service Road', True), ('Service', True), ('Alley', False)]:
            with self.subTest(returned_type=returned_type):
                payloads = [self.typed_response('Street'), self.typed_response(returned_type),
                            self.typed_response('Ramp')]
                session = Mock()
                session.get.side_effect = [Mock(json=Mock(return_value=raw)) for raw in payloads]
                with patch.object(f.e, 'client') as factory:
                    factory.return_value.__enter__.return_value = session
                    result = f.get_typed_lrs({'geometry': {'x': 1, 'y': 2}})
                self.assertEqual('error' not in result, succeeds)
                self.assertEqual(result['typed_responses']['Service'], payloads[1])
                if succeeds:
                    self.assertEqual(result['pointOnSubBlocks'][1]['routeType'], returned_type)

    def test_new_point_still_uses_all_route_lookup(self):
        feature = {'geometry': {'x': 1, 'y': 2}}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(f, 'get_lrs', return_value={'pointOnSubBlocks': []}) as lookup, \
                    patch.object(f, 'get_typed_lrs') as fallback:
                f.capture_lrs(Path(directory), [feature], resume=True)
            lookup.assert_called_once_with(feature)
            fallback.assert_not_called()

    def test_eligible_types_flag_routes_new_points_without_fake_prior_error(self):
        feature = {'geometry': {'x': 1, 'y': 2}}
        existing = {'geometry': {'x': 3, 'y': 4}}
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            f.atomic_save(snapshot / 'lrs.json', {f.e.point_key(existing): {'pointOnSubBlocks': []}})
            with patch.object(f, 'get_lrs') as all_lookup, \
                    patch.object(f, 'get_typed_lrs', return_value={'pointOnSubBlocks': []}) as typed:
                f.capture_lrs(snapshot, [existing, feature], resume=True, eligible_types=True)
            all_lookup.assert_not_called()
            typed.assert_called_once_with(feature, None)
        session = Mock()
        session.get.side_effect = [Mock(json=Mock(return_value=self.typed_response(kind)))
                                   for kind in ('Street', 'Service', 'Ramp')]
        with patch.object(f.e, 'client') as factory:
            factory.return_value.__enter__.return_value = session
            response = f.get_typed_lrs(feature)
        self.assertNotIn('original_all_error', response)
        self.assertNotIn('error', response)
        self.assertEqual(f.get_typed_lrs({'geometry': None})['retryable'], False)

    def test_unavailable_is_not_an_empty_success(self):
        self.assertEqual(f.get_lrs({'geometry': None}), {
            'error': 'Missing point geometry', 'unavailable': True, 'retryable': False})

    def test_http_200_status_error_is_saved_as_retryable_lrs_failure(self):
        payload = {'status': 'error', 'messages': [
            'Could not access any server machines. Please contact your system administrator.']}
        session = Mock()
        session.get.return_value = Mock(json=Mock(return_value=payload))
        with patch.object(f.e, 'client') as factory:
            factory.return_value.__enter__.return_value = session
            result = f.get_lrs({'geometry': {'x': -77, 'y': 39}})
        self.assertTrue(result['unavailable'])
        self.assertTrue(result['retryable'])
        self.assertIn(payload['messages'][0], result['error'])
        self.assertNotIn('pointOnSubBlocks', result)


if __name__ == '__main__':
    unittest.main()
