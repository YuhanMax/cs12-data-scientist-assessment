"""Capture the complete 2026 cohort, with resumable unique-point LRS lookup."""
import argparse
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

if __package__:
    from . import enrich_permits as e
else:
    import enrich_permits as e


def atomic_save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    e.save(temporary, value)
    os.replace(temporary, path)


def value_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False).encode('utf-8')).hexdigest()


def complete_rows(session, url, where):
    """Reconcile the count, ID enumeration, each batch, and final membership."""
    count = e.query(session, url, where, returnCountOnly='true')['count']
    listing = e.query(session, url, where, returnIdsOnly='true')
    ids = listing.get('objectIds') or []
    e.require(not listing.get('exceededTransferLimit'), 'Truncated ID enumeration')
    e.require(len(ids) == len(set(ids)) == count, 'Source count/ID mismatch')
    oid = listing.get('objectIdFieldName', 'OBJECTID')
    features = []
    for offset in range(0, len(ids), 200):
        batch = ids[offset:offset + 200]
        response = e.query(session, url, where, objectIds=','.join(map(str, batch)),
                           outFields='*', returnGeometry='true', outSR=4326)
        e.require(not response.get('exceededTransferLimit'), 'Truncated feature batch')
        rows = response['features']
        e.require(Counter(f['attributes'][oid] for f in rows) == Counter(batch),
                  'Feature batch ID mismatch')
        features.extend(rows)
    final_ids = e.query(session, url, where, returnIdsOnly='true')
    e.require(not final_ids.get('exceededTransferLimit') and
              Counter(final_ids.get('objectIds') or []) == Counter(ids),
              'Source membership changed during capture; retry acquisition')
    return sorted(features, key=lambda f: f['attributes'][oid])


def get_lrs(feature):
    geometry = feature.get('geometry')
    if not geometry or 'x' not in geometry or 'y' not in geometry:
        return {'error': 'Missing point geometry', 'unavailable': True, 'retryable': False}
    try:
        with e.client() as session:
            response = e.api(session, e.LRS, x=geometry['x'], y=geometry['y'], inSR=4326,
                             outSR=4326, includeSectionEvents='false',
                             returnNearestMatchOnly='false', searchRadius=50)
        e.require(isinstance(response.get('pointOnSubBlocks'), list), 'Malformed LRS response')
        return response
    except (requests.RequestException, ValueError) as error:
        return {'error': str(error), 'unavailable': True, 'retryable': True,
                'attempted_utc': datetime.now(timezone.utc).isoformat()}


def get_typed_lrs(feature, previous=None):
    """Retry a saved All-route failure without changing the eligible search set."""
    geometry = feature.get('geometry')
    if not geometry or 'x' not in geometry or 'y' not in geometry:
        return {'error': 'Missing point geometry', 'unavailable': True, 'retryable': False}
    result = {'lookup_method': 'explicit_eligible_route_types_v1',
              'typed_responses': {}, 'attempted_utc': datetime.now(timezone.utc).isoformat()}
    if previous is not None:
        if 'original_all_error' in previous:
            result['original_all_error'] = previous['original_all_error']
        elif previous.get('lookup_method') != 'explicit_eligible_route_types_v1':
            result['original_all_error'] = previous
    errors = []
    with e.client() as session:
        for route_type in ('Street', 'Service', 'Ramp'):
            try:
                response = session.get(e.LRS, params={'f': 'json', 'x': geometry['x'],
                    'y': geometry['y'], 'inSR': 4326, 'outSR': 4326,
                    'includeSectionEvents': 'false', 'returnNearestMatchOnly': 'false',
                    'searchRadius': 50, 'routeType': route_type}, timeout=(10, 60))
                raw = response.json()
                result['typed_responses'][route_type] = raw
                response.raise_for_status()
                e.validate_response(raw)
                e.require(isinstance(raw.get('pointOnSubBlocks'), list), 'Malformed typed LRS response')
                accepted = {'Service', 'Service Road'} if route_type == 'Service' else {route_type}
                e.require(all(isinstance(p, dict) and p.get('routeType') in accepted
                              for p in raw['pointOnSubBlocks']), 'Unexpected typed LRS candidate')
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                result['typed_responses'].setdefault(route_type, {'error': str(error)})
                errors.append(route_type + ': ' + str(error))
    if errors:
        result.update(error='; '.join(errors), unavailable=True, retryable=True)
    else:
        result['pointOnSubBlocks'] = [p for route_type in ('Street', 'Service', 'Ramp')
                                     for p in result['typed_responses'][route_type]['pointOnSubBlocks']]
    return result


def capture_lrs(snapshot, permits, resume=False, eligible_types=False):
    path = snapshot / 'lrs.json'
    responses = e.load(path) if path.exists() else {}
    unique = {e.point_key(feature): feature for feature in permits}
    e.require(set(responses) <= set(unique), 'Checkpoint contains unknown permit points')
    pending = {key: feature for key, feature in unique.items()
               if key not in responses or ('error' in responses[key] and
                                            responses[key].get('retryable', True))}
    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {}
            for key, feature in pending.items():
                if eligible_types or (resume and key in responses and 'error' in responses[key]):
                    future = executor.submit(get_typed_lrs, feature, responses.get(key))
                else:
                    future = executor.submit(get_lrs, feature)
                futures[future] = key
            for completed, future in enumerate(as_completed(futures), 1):
                responses[futures[future]] = future.result()
                if completed % 25 == 0:
                    atomic_save(path, responses)
                    print(f'LRS checkpoint: {len(responses)}/{len(unique)} unique points', flush=True)
    finally:
        atomic_save(path, responses)
    if not path.exists():
        atomic_save(path, responses)
    return responses


def application_context(session, permits):
    """Audit whole tracking-number groups without expanding output membership."""
    applications = sorted({p['attributes']['TrackingNumber'] for p in permits})
    eligible_ids = {p['attributes']['OBJECTID'] for p in permits}
    complete_ids = set()
    extras = []
    started = datetime.now(timezone.utc).isoformat()
    for offset in range(0, len(applications), 100):
        where = 'TrackingNumber IN (' + ','.join(map(str, applications[offset:offset + 100])) + ')'
        count = e.query(session, e.PERMITS, where, returnCountOnly='true')['count']
        listing = e.query(session, e.PERMITS, where, returnIdsOnly='true')
        ids = listing.get('objectIds') or []
        e.require(not listing.get('exceededTransferLimit') and len(ids) == len(set(ids)) == count,
                  'Application context count/ID mismatch')
        complete_ids.update(ids)
        missing = sorted(set(ids) - eligible_ids)
        for start in range(0, len(missing), 200):
            rows = complete_rows(session, e.PERMITS,
                                 'OBJECTID IN (' + ','.join(map(str, missing[start:start + 200])) + ')')
            e.require({r['attributes']['OBJECTID'] for r in rows} == set(missing[start:start + 200]),
                      'Application context IDs changed')
            extras.extend(rows)
        final = e.query(session, e.PERMITS, where, returnIdsOnly='true')
        e.require(not final.get('exceededTransferLimit') and
                  Counter(final.get('objectIds') or []) == Counter(ids),
                  'Application group membership changed during capture')
    e.require(eligible_ids <= complete_ids, 'Eligible locations missing from full application groups')
    all_rows = permits + extras
    groups = {str(t): {'eligible_object_ids': sorted(p['attributes']['OBJECTID'] for p in permits
                                                   if p['attributes']['TrackingNumber'] == t),
                      'complete_object_ids': sorted(p['attributes']['OBJECTID'] for p in all_rows
                                                   if p['attributes']['TrackingNumber'] == t)}
              for t in applications}
    for group in groups.values():
        group['filtered_group_complete'] = group['eligible_object_ids'] == group['complete_object_ids']
    return {'features': sorted(extras, key=lambda p: p['attributes']['OBJECTID']), 'groups': groups,
            'source_retrieval_started_utc': started,
            'source_retrieval_finished_utc': datetime.now(timezone.utc).isoformat(),
            'membership_rechecked': True}


def fetch(snapshot, resume=False, eligible_types=False):
    e.require(resume or not snapshot.exists(), 'Snapshot exists; use --resume or a new name')
    snapshot.mkdir(parents=True, exist_ok=True)
    # Remove completion before retrying saved failures, so interruption is explicit.
    complete = snapshot / '.fetch_complete'
    if complete.exists():
        complete.unlink()
    with e.client() as session:
        permit_path = snapshot / 'permits.json'
        if permit_path.exists():
            source = e.load(permit_path)
            e.require(source.get('acquisition_filter') == e.FILTER, 'Checkpoint filter changed')
            cohort = e.load(snapshot / 'date_type_cohort.json')
        else:
            source_started = datetime.now(timezone.utc).isoformat()
            metadata = e.api(session, e.PERMITS)
            e.validate_metadata(metadata, ['OBJECTID', 'TrackingNumber', 'LocationID',
                                           'ApplicationDate', 'IssueDate', 'ApplicantCompany'])
            e.require(metadata.get('dateFieldsTimeReference', {}).get('timeZoneIANA') ==
                      'America/New_York', 'Unexpected source timezone')
            rows = complete_rows(session, e.PERMITS, e.DATE_SQL + ' AND ' + e.TYPE_SQL)
            cohort = {'metadata': metadata, 'query_output_spatial_reference': {'wkid': 4326},
                      'filter': e.DATE_SQL + ' AND ' + e.TYPE_SQL, 'features': rows}
            permits = [f for f in rows if e.qualifies(f['attributes'])]
            exact_ids = e.query(session, e.PERMITS, e.FILTER, returnIdsOnly='true')
            e.require(not exact_ids.get('exceededTransferLimit') and
                      Counter(exact_ids.get('objectIds') or []) ==
                      Counter(f['attributes']['OBJECTID'] for f in permits),
                      'Exact FILTER membership differs from captured cohort')
            source = {'metadata': metadata, 'query_output_spatial_reference': {'wkid': 4326},
                      'acquisition_filter': e.FILTER, 'features': permits,
                      'source_retrieval_started_utc': source_started,
                      'source_retrieval_finished_utc': datetime.now(timezone.utc).isoformat(),
                      'controls': [{'reason': 'utility', 'feature': f} for f in rows
                                   if not e.qualifies(f['attributes'])]}
            atomic_save(snapshot / 'date_type_cohort.json', cohort)
            atomic_save(permit_path, source)
        permits = source['features']
        context_path = snapshot / 'application_context.json'
        if context_path.exists() and e.load(context_path).get('membership_rechecked'):
            context = e.load(context_path)
        else:
            context = application_context(session, permits)
            context.update(metadata=source['metadata'], query_output_spatial_reference={'wkid': 4326})
            atomic_save(context_path, context)
        print(f'Captured {len(permits)} exact-filter locations; '
              f'{len(cohort["features"])} date/type locations', flush=True)
        lrs = capture_lrs(snapshot, permits, resume=resume, eligible_types=eligible_types)
        keys = sorted({p['subBlockKey'] for response in lrs.values()
                       for p in response.get('pointOnSubBlocks', [])
                       if p.get('routeType') in {'Street', 'Service', 'Service Road', 'Ramp'} and p.get('subBlockKey')})
        road_metadata = e.api(session, e.ROADS)
        e.validate_metadata(road_metadata, ['SUBBLOCKKEY', 'ROADTYPE', 'FHWAFUNCTIONALCLASS'])
        roads = []
        for offset in range(0, len(keys), 100):
            predicate = 'SUBBLOCKKEY IN (' + ','.join("'" + k.replace("'", "''") + "'"
                                                    for k in keys[offset:offset + 100]) + ')'
            roads.extend(complete_rows(session, e.ROADS, predicate))
        actual_keys = [f['attributes']['SUBBLOCKKEY'] for f in roads]
        e.require(len(actual_keys) == len(set(actual_keys)), 'Duplicate road key')
        e.require(set(actual_keys) <= set(keys), 'Unrequested road key')
        atomic_save(snapshot / 'roads.json', {'metadata': road_metadata,
                    'query_output_spatial_reference': {'wkid': 4326}, 'features': roads})
    applications = sorted({f['attributes']['TrackingNumber'] for f in permits})
    memberships = {str(t): sorted(f['attributes']['OBJECTID'] for f in permits
                                 if f['attributes']['TrackingNumber'] == t) for t in applications}
    identities = [[f['attributes'].get(k) for k in ('OBJECTID', 'TrackingNumber', 'LocationID')]
                  for f in permits]
    files = ['permits.json', 'lrs.json', 'roads.json', 'date_type_cohort.json', 'application_context.json']
    atomic_save(snapshot / 'manifest.json', {
        'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'filter': e.FILTER,
        'source_retrieval_started_utc': source.get('source_retrieval_started_utc'),
        'source_retrieval_finished_utc': source.get('source_retrieval_finished_utc'),
        'selection': 'complete exact FILTER cohort', 'selected_applications': applications,
        'whole_application_object_ids': memberships,
        'application_group_audit': context['groups'],
        'filtered_incomplete_applications': sorted(t for t, group in context['groups'].items()
                                                  if not group['filtered_group_complete']),
        'identity_sha256': value_hash(identities), 'membership_sha256': value_hash(memberships),
        'source_urls': {'permits': e.PERMITS, 'roads': e.ROADS, 'lrs': e.LRS}, 'out_fields': '*',
        'road_key_coverage': {'requested': keys, 'returned': sorted(actual_keys),
                              'missing': sorted(set(keys) - set(actual_keys))},
        'lrs_unavailable_points': sum('error' in response for response in lrs.values()),
        'lrs_typed_fallback_points': sum(response.get('lookup_method') ==
                                         'explicit_eligible_route_types_v1' for response in lrs.values()),
        'hashes': {name: e.digest(snapshot / name) for name in files}})
    complete.touch()
    print(f'Saved {len(permits)} locations / {len(applications)} applications to {snapshot}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--eligible-types', action='store_true',
                        help='Use separate complete Street/Service/Ramp queries for pending points')
    args = parser.parse_args()
    fetch(e.checked_path(args.snapshot), args.resume, args.eligible_types)
