"""Enrich full-column occupancy snapshots; run and independently verify offline."""
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if __package__:
    from . import supplemental, supplemental_verify
else:
    import supplemental
    import supplemental_verify

ROOT = Path(__file__).resolve().parent.parent / 'artifacts'
RESOLUTION_PATH = Path(__file__).resolve().parent.parent / 'config' / 'case_resolutions.json'
RESOLUTIONS = json.loads(RESOLUTION_PATH.read_text(encoding='utf-8'))
RESOLUTION_SHA256 = '9AFA28B8EFE7EE56D3810C1DFBC2BEE73F7D7516062E38D99DEA8677E5D15AE3'
PERMITS = 'https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/DDOT_TOPS/MapServer/24'
ROADS = 'https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/162'
LRS = 'https://rh.dcgis.dc.gov/dcgis/rest/services/DDOT/RoadwayBlocks/MapServer/exts/DdotLrsExtensions/getPointOnSubBlock'
MAR = 'https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Location_WebMercator/FeatureServer/0'
ALIASES = {'DCWater': 'DC Water', 'DCWater/CIP': 'DC Water', 'DCWater/OPS': 'DC Water',
           'Potomac Electric Power Company': 'PEPCO', 'Pepco': 'PEPCO',
           'Wash Gas & Light Co.': 'Washington Gas'}
TYPES = {'Construction Staging Area', 'Mobile Crane Work Zone'}
# Both local January boundaries are UTC-05; returned ArcGIS dates are UTC milliseconds.
START = int(datetime(2026, 1, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2027, 1, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
DATE_SQL = "((ApplicationDate >= TIMESTAMP '2026-01-01 00:00:00' AND ApplicationDate < TIMESTAMP '2027-01-01 00:00:00') OR (IssueDate >= TIMESTAMP '2026-01-01 00:00:00' AND IssueDate < TIMESTAMP '2027-01-01 00:00:00'))"
TYPE_SQL = "EventTypeDescription IN ('Construction Staging Area','Mobile Crane Work Zone')"
UTILITY_SQL = 'ApplicantCompany IN (' + ','.join("'" + x + "'" for x in ALIASES) + ')'
FILTER = DATE_SQL + ' AND ' + TYPE_SQL + ' AND ' + UTILITY_SQL
LABELS = {1: 'Interstate', 2: 'Principal Arterial - Other Freeways or Expressways',
          3: 'Principal Arterial - Other', 4: 'Minor Arterial', 5: 'Major Collector',
          6: 'Minor Collector', 7: 'Local'}
MATCH_POLICY = 'nearest_50m_intersection_consensus_exact_mar_v5'
ELIGIBLE_ROUTES = {'Street', 'Service', 'Service Road', 'Ramp'}
ADDRESS_REASON = 'unique_exact_unit_block_nearest_street'
ADDRESS_BASIS = ('Unique exact range address among eligible candidates within 50 m; nearest candidate is '
                 'Street and roadway key, route name, Street type and valid FHWA class agree.')
DERIVED = ['geometry_json', 'geometry_x', 'geometry_y', 'utility', 'subblock_key',
           'road_name', 'road_type', 'distance_m', 'candidate_count', 'match_status',
           'match_reason', 'fhwa_code', 'fhwa_name', 'highest_known_code',
           'highest_known_name', 'application_locations', 'matched_locations',
           'application_complete', 'application_highest_code', 'application_highest_name',
           'resolution_id', 'resolution_basis', 'class_method',
           'supporting_subblock_keys', 'evidence_reference']


def checked_path(value):
    path = Path(value)
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if path == ROOT.resolve() or ROOT.resolve() not in path.parents:
        raise ValueError('Snapshot/output must be a child directory of artifacts')
    return path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_response(value):
    require(isinstance(value, dict), 'Expected JSON object')
    if value.get('status') == 'error':
        raise ValueError('API error: ' + str(value.get('messages')))
    require('error' not in value and value.get('Success') is not False,
            'API error: ' + str(value.get('error', value.get('Message'))))
    return value


def client():
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5,
                  status_forcelist=[429, 500, 502, 503, 504])))
    return session


def api(session, url, **params):
    response = session.get(url, params={'f': 'json', **params}, timeout=(10, 60))
    response.raise_for_status()
    return validate_response(response.json())


def query(session, url, where, **params):
    return api(session, url + '/query', where=where, **params)


def all_rows(session, url, where):
    ids = query(session, url, where, returnIdsOnly='true').get('objectIds') or []
    features = []
    for offset in range(0, len(ids), 1000):
        response = query(session, url, '1=1', objectIds=','.join(map(str, ids[offset:offset+1000])),
                         outFields='*', returnGeometry='true', outSR=4326)
        require(not response.get('exceededTransferLimit'), 'Truncated ID batch')
        features.extend(response['features'])
    require(Counter(f['attributes']['OBJECTID'] for f in features) == Counter(ids), 'ID coverage mismatch')
    return sorted(features, key=lambda f: f['attributes']['OBJECTID'])


def qualifies(attrs):
    return (attrs.get('ApplicantCompany') in ALIASES and attrs.get('EventTypeDescription') in TYPES
            and any(value is not None and START <= value < END
                    for value in [attrs.get('ApplicationDate'), attrs.get('IssueDate')]))


def point_key(feature):
    return json.dumps(feature.get('geometry'), sort_keys=True, separators=(',', ':'))


def validate_metadata(metadata, required):
    fields = {f['name']: f for f in metadata.get('fields', [])}
    require(set(required) <= fields.keys(), 'Missing required metadata fields')
    return fields


def fetch(snapshot):
    require(not snapshot.exists(), 'Snapshot already exists; use a new snapshot name')
    session = client()
    metadata = api(session, PERMITS)
    validate_metadata(metadata, ['OBJECTID', 'TrackingNumber', 'LocationID', 'ApplicationDate', 'IssueDate'])
    require(metadata.get('dateFieldsTimeReference', {}).get('timeZoneIANA') == 'America/New_York',
            'Unexpected source timezone; review date boundaries')
    road_metadata = api(session, ROADS)
    validate_metadata(road_metadata, ['SUBBLOCKKEY', 'ROADTYPE', 'FHWAFUNCTIONALCLASS'])
    chosen = {11182457, 11197669}
    selection = []
    for alias in ALIASES:
        candidates = []
        for order in ['Longitude ASC', 'Longitude DESC']:
            response = query(session, PERMITS, FILTER + " AND ApplicantCompany='" + alias + "'",
                             outFields='*', returnGeometry='true', outSR=4326,
                             orderByFields=order + ',OBJECTID', resultRecordCount=20)
            candidates.extend(response['features'])
        unique = list(dict.fromkeys(f['attributes']['TrackingNumber'] for f in candidates))
        # Both geographic extremes enter before remaining application IDs.
        picks = list(dict.fromkeys(unique[:2] + unique[-2:]))
        chosen.update(picks)
        selection.append({'alias': alias, 'chosen_tracking_numbers': picks})
    # Ensure a pending/unissued application participates in the real pilot.
    pending = query(session, PERMITS, FILTER + ' AND PermitNumber IS NULL', outFields='*',
                    returnGeometry='true', outSR=4326, resultRecordCount=1)['features']
    if pending:
        chosen.add(pending[0]['attributes']['TrackingNumber'])
    where = 'TrackingNumber IN (' + ','.join(map(str, sorted(chosen))) + ')'
    permits = all_rows(session, PERMITS, where)
    require(all(qualifies(f['attributes']) for f in permits), 'Selected application includes nonqualifying locations')
    controls = []
    control_queries = {'type': DATE_SQL + ' AND ' + UTILITY_SQL + ' AND NOT (' + TYPE_SQL + ')',
                       'utility': DATE_SQL + ' AND ' + TYPE_SQL + ' AND NOT (' + UTILITY_SQL + ')',
                       'date': "(ApplicationDate IS NULL OR ApplicationDate < TIMESTAMP '2026-01-01 00:00:00' OR ApplicationDate >= TIMESTAMP '2027-01-01 00:00:00')" +
                       " AND (IssueDate IS NULL OR IssueDate < TIMESTAMP '2026-01-01 00:00:00' OR IssueDate >= TIMESTAMP '2027-01-01 00:00:00')"}
    for reason, predicate in control_queries.items():
        rows = query(session, PERMITS, predicate, outFields='*', returnGeometry='true', outSR=4326,
                     orderByFields='OBJECTID', resultRecordCount=1)['features']
        require(rows, 'Missing negative control: ' + reason)
        controls.append({'reason': reason, 'feature': rows[0]})
    lrs = {}
    for index, feature in enumerate(permits):
        key = point_key(feature)
        if key in lrs:
            continue
        geometry = feature.get('geometry')
        if not geometry:
            lrs[key] = {'error': 'Missing geometry'}
            continue
        try:
            lrs[key] = api(session, LRS, x=geometry['x'], y=geometry['y'], inSR=4326, outSR=4326,
                           includeSectionEvents='false', returnNearestMatchOnly='false', searchRadius=50)
        except (requests.RequestException, ValueError) as error:
            lrs[key] = {'error': str(error)}
        print(f'LRS {index+1}/{len(permits)}', flush=True)
    keys = sorted({p['subBlockKey'] for response in lrs.values() for p in response.get('pointOnSubBlocks', [])
                   if p.get('routeType') in ELIGIBLE_ROUTES and p.get('subBlockKey')})
    roads = []
    for offset in range(0, len(keys), 100):
        predicate = 'SUBBLOCKKEY IN (' + ','.join("'" + x + "'" for x in keys[offset:offset+100]) + ')'
        roads.extend(all_rows(session, ROADS, predicate))
    snapshot.mkdir(parents=True)
    save(snapshot / 'permits.json', {'metadata': metadata, 'query_output_spatial_reference': {'wkid': 4326},
                                    'features': permits, 'controls': controls})
    save(snapshot / 'lrs.json', lrs)
    save(snapshot / 'roads.json', {'metadata': road_metadata, 'query_output_spatial_reference': {'wkid': 4326},
                                  'features': roads})
    save(snapshot / 'manifest.json', {'retrieved_utc': datetime.now(timezone.utc).isoformat(),
         'filter': FILTER, 'selection': selection, 'selected_applications': sorted(chosen),
         'whole_application_object_ids': {str(t): sorted(f['attributes']['OBJECTID'] for f in permits
                                        if f['attributes']['TrackingNumber'] == t) for t in chosen},
         'source_urls': {'permits': PERMITS, 'roads': ROADS, 'lrs': LRS}, 'out_fields': '*',
         'hashes': {name: digest(snapshot / name) for name in ['permits.json', 'lrs.json', 'roads.json']}})
    (snapshot / '.fetch_complete').touch()
    print(f'Saved {len(permits)} locations / {len(chosen)} complete applications to {snapshot}')


def numbered_street(address):
    """Extract only an explicit numbered street address, including its DC quadrant."""
    suffixes = {'ST': 'STREET', 'AVE': 'AVENUE', 'RD': 'ROAD', 'DR': 'DRIVE',
                'PL': 'PLACE', 'CT': 'COURT', 'BLVD': 'BOULEVARD', 'TER': 'TERRACE',
                'CIR': 'CIRCLE', 'PKWY': 'PARKWAY', 'LN': 'LANE', 'WAY': 'WAY'}
    text = ' '.join(address.upper().replace('.', '').split())
    # shortcut: only conventional numbered DC addresses, expand with reviewed evidence.
    parsed = re.fullmatch(r'\d+[A-Z]? (?:- \d+ )?(?:BLOCK OF )?([A-Z0-9 -]+) (NE|NW|SE|SW)', text)
    if not parsed:
        return None
    words = parsed[1].split()
    suffix = suffixes.get(words[-1], words[-1])
    if len(words) < 2 or suffix not in suffixes.values():
        return None
    return (' '.join(words[:-1]), suffix, parsed[2])


def match(feature, response, roads, allow_case_resolutions=True):
    result = {'match_status': 'unresolved', 'match_reason': '', 'candidate_count': 0,
              'subblock_key': '', 'road_name': '', 'road_type': '', 'distance_m': '',
              'fhwa_code': '', 'fhwa_name': '', 'resolution_id': '', 'resolution_basis': ''}
    if not feature.get('geometry'):
        result['match_reason'] = 'missing_geometry'
        return result
    if 'error' in response or response.get('unavailable') or response.get('Success') is False:
        result['match_reason'] = 'service_error'
        return result
    require('pointOnSubBlocks' in response, 'Malformed LRS response')
    candidates = [p for p in response['pointOnSubBlocks'] if p.get('routeType') in ELIGIBLE_ROUTES]
    result['candidate_count'] = len(candidates)
    candidates = [p for p in candidates if isinstance(p.get('offsetInMeters'), (int, float))
                  and math.isfinite(p['offsetInMeters']) and 0 <= p['offsetInMeters'] <= 50]
    if not candidates:
        result['match_reason'] = 'no_eligible_road_within_50m'
        return result
    candidates.sort(key=lambda p: (p['offsetInMeters'], p['subBlockKey']))
    nearest = candidates[0]
    result.update(subblock_key=nearest['subBlockKey'], road_name=nearest.get('routeName', ''),
                  distance_m=nearest['offsetInMeters'])
    attrs = roads.get(nearest['subBlockKey'])
    address = feature['attributes'].get('WorkLocationFullAddress') or ''
    exact_blocks = [p for p in candidates if p.get('unitBlock') == address]
    address_supported = ('BLOCK OF' in address and len(exact_blocks) == 1 and exact_blocks[0] is nearest
                         and nearest.get('routeType') == 'Street' and attrs is not None
                         and attrs.get('SUBBLOCKKEY') == nearest['subBlockKey']
                         and attrs.get('ROUTENAME') == nearest.get('routeName')
                         and str(attrs.get('ROADTYPE')) == '1'
                         and type(attrs.get('FHWAFUNCTIONALCLASS')) is int
                         and attrs['FHWAFUNCTIONALCLASS'] in LABELS)
    reviewed = (allow_case_resolutions and address_supported and
                any(all(feature['attributes'].get(k) == v for k, v in case.items())
                    for case in RESOLUTIONS['cases']) and
                feature['geometry'] == RESOLUTIONS['geometry'] and address == RESOLUTIONS['address'] and
                len(exact_blocks) == 1 and exact_blocks[0] is nearest and
                nearest['subBlockKey'] == RESOLUTIONS['subblock_key'] and
                nearest.get('routeName') == RESOLUTIONS['road_name'] and nearest.get('routeType') == 'Street' and
                attrs is not None and str(attrs.get('ROADTYPE')) == RESOLUTIONS['road_type'] and
                type(attrs.get('FHWAFUNCTIONALCLASS')) is int and
                attrs['FHWAFUNCTIONALCLASS'] == RESOLUTIONS['fhwa_code'])
    ambiguous = any(p.get('routeName') != nearest.get('routeName') and
                    p['offsetInMeters'] - nearest['offsetInMeters'] <= 1 for p in candidates[1:])
    if ambiguous and len(exact_blocks) > 1:
        result['match_reason'] = 'multiple_exact_unit_blocks'
        return result
    if ambiguous and not (reviewed or address_supported):
        result['match_reason'] = 'ambiguous_different_roads_within_1m'
        return result
    if attrs is None:
        result['match_reason'] = 'missing_subblock_lookup'
        return result
    if attrs.get('SUBBLOCKKEY') != nearest['subBlockKey'] or (
            attrs.get('ROUTENAME') is not None and attrs['ROUTENAME'] != nearest.get('routeName')):
        result['match_reason'] = 'roadway_identity_disagreement'
        return result
    result['road_type'] = attrs.get('ROADTYPE', '')
    if str(attrs.get('ROADTYPE')) not in {'1', '2', '3'}:
        result['match_reason'] = 'ineligible_roadway_type'
        return result
    code = attrs.get('FHWAFUNCTIONALCLASS')
    if type(code) is not int or code not in LABELS:
        result['match_reason'] = 'missing_or_invalid_fhwa_class'
        return result
    # Unit-block strings give an exact check for the range-address locations.
    if 'BLOCK OF' in address and nearest.get('unitBlock') != address:
        result['match_reason'] = 'unit_block_disagreement'
        return result
    address_street = numbered_street(address)
    nearest_street = numbered_street(nearest.get('unitBlock') or '')
    if address_street and nearest_street and address_street != nearest_street:
        result['match_reason'] = 'named_street_disagreement'
        return result
    result.update(match_status='matched', match_reason='nearest_eligible_road', fhwa_code=code,
                  fhwa_name=LABELS[code])
    if ambiguous and reviewed:
        result.update(match_reason=RESOLUTIONS['policy'],
                      resolution_id='python_oid_' + str(feature['attributes']['OBJECTID']),
                      resolution_basis=RESOLUTIONS['evidence'])
    elif ambiguous and address_supported:
        result.update(match_reason=ADDRESS_REASON,
                      resolution_id=MATCH_POLICY + ':oid_' + str(feature['attributes']['OBJECTID']),
                      resolution_basis=ADDRESS_BASIS)
    return result


def source_cell(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def supplemental_evidence(snapshot):
    """Load hashed, source-labelled MAR responses without changing frozen inputs."""
    manifest = load(snapshot / 'manifest.json')
    path = snapshot / 'mar_evidence.json'
    hashed = 'mar_evidence.json' in manifest.get('hashes', {})
    require(hashed == path.exists(), 'Unhashed or missing supplemental evidence')
    if not hashed:
        return None
    require(digest(path) == manifest['hashes']['mar_evidence.json'], 'MAR evidence hash mismatch')
    evidence = load(path)
    require(evidence.get('source_url') == MAR and evidence.get('road_source_url') == ROADS,
            'Unexpected supplemental source')
    require('base_manifest.json' in manifest['hashes'], 'Unhashed supplemental base manifest')
    require(digest(snapshot / 'base_manifest.json') == manifest['hashes']['base_manifest.json'] ==
            evidence.get('base_snapshot_sha256'), 'Wrong supplemental base snapshot')
    base = load(snapshot / 'base_manifest.json')
    require(all(manifest['hashes'].get(name) == expected for name, expected in base['hashes'].items()),
            'Frozen source hash changed in supplemental snapshot')
    collected = {MAR + '/query': [], ROADS + '/query': []}
    queries = evidence.get('queries')
    require(isinstance(queries, list) and queries, 'Missing raw supplemental queries')
    for query_record in queries:
        require(isinstance(query_record, dict) and query_record.get('url') in collected,
                'Unexpected supplemental query URL')
        timestamp = datetime.fromisoformat(query_record.get('retrieved_utc', ''))
        require(timestamp.tzinfo is not None, 'Supplemental retrieval time must include timezone')
        params = query_record.get('params', {})
        require(params.get('outSR') == 4326 and params.get('returnGeometry') == 'true',
                'Wrong supplemental geometry reference')
        value = validate_response(query_record.get('response'))
        require(not value.get('exceededTransferLimit') and isinstance(value.get('features'), list),
                'Truncated or malformed supplemental response')
        collected[query_record['url']].extend(value['features'])
    require(evidence.get('address_features') == collected[MAR + '/query'] and
            evidence.get('road_features') == collected[ROADS + '/query'],
            'Supplemental evidence differs from raw queries')
    return evidence


def inputs(snapshot):
    require(digest(RESOLUTION_PATH).upper() == RESOLUTION_SHA256,
            'Case resolution policy changed; review and pin a new policy hash')
    manifest = load(snapshot / 'manifest.json')
    cohort_name = 'date_type_cohort.json'
    full_cohort = (manifest.get('selection') == 'complete exact FILTER cohort' or
                   cohort_name in manifest['hashes'] or (snapshot / cohort_name).exists())
    if full_cohort:
        require(cohort_name in manifest['hashes'] and (snapshot / cohort_name).is_file(),
                'Full snapshot requires a hashed date/type cohort')
    for name, expected in manifest['hashes'].items():
        component = (snapshot / name).resolve()
        require(snapshot.resolve() in component.parents, 'Snapshot component outside snapshot')
        require(digest(component) == expected, 'Snapshot hash mismatch: ' + name)
    permits = load(snapshot / 'permits.json')
    if full_cohort:
        cohort = load(snapshot / cohort_name)['features']
        expected_permits, expected_controls = {}, {}
        for feature in cohort:
            attrs = feature['attributes']
            oid = attrs['OBJECTID']
            require(oid not in expected_permits and oid not in expected_controls,
                    'Duplicate date/type cohort OBJECTID')
            # Reconstruct the documented filter independently of the producer's qualifies().
            date_matches = ((attrs.get('ApplicationDate') is not None and
                             START <= attrs['ApplicationDate'] < END) or
                            (attrs.get('IssueDate') is not None and START <= attrs['IssueDate'] < END))
            require(date_matches and attrs.get('EventTypeDescription') in
                    {'Construction Staging Area', 'Mobile Crane Work Zone'},
                    'Unexpected date/type cohort feature')
            partition = expected_permits if attrs.get('ApplicantCompany') in ALIASES else expected_controls
            partition[oid] = feature
        for features, expected in [(permits['features'], expected_permits),
                                    ([c['feature'] for c in permits['controls']], expected_controls)]:
            actual = {f['attributes']['OBJECTID']: f for f in features}
            require(len(actual) == len(features), 'Duplicate cohort partition OBJECTID')
            require(actual == expected, 'Full cohort partition membership or feature mismatch')
    lrs = load(snapshot / 'lrs.json')
    for response in lrs.values():
        require(isinstance(response, dict), 'Malformed LRS response')
        if 'error' not in response and not response.get('unavailable'):
            validate_response(response)
            require(isinstance(response.get('pointOnSubBlocks'), list) and
                    all(isinstance(p, dict) for p in response['pointOnSubBlocks']),
                    'Malformed LRS response')
        if response.get('lookup_method') == 'explicit_eligible_route_types_v1' and not (
                'error' in response or response.get('unavailable')):
            typed = response.get('typed_responses')
            require(isinstance(typed, dict) and set(typed) == {'Street', 'Service', 'Ramp'},
                    'Incomplete typed LRS fallback')
            combined = []
            for kind in ('Street', 'Service', 'Ramp'):
                raw = typed[kind]
                require(isinstance(raw, dict) and 'error' not in raw and not raw.get('unavailable')
                        and raw.get('Success') is not False and isinstance(raw.get('pointOnSubBlocks'), list),
                        'Failed or malformed typed LRS fallback: ' + kind)
                allowed = {'Service', 'Service Road'} if kind == 'Service' else {kind}
                require(all(isinstance(p, dict) and p.get('routeType') in allowed
                            for p in raw['pointOnSubBlocks']), 'Wrong typed LRS candidate type: ' + kind)
                combined.extend(raw['pointOnSubBlocks'])
            require(response.get('pointOnSubBlocks') == combined, 'Typed LRS aggregate mismatch')
    roads = load(snapshot / 'roads.json')
    if 'application_group_audit' in manifest:
        require('application_context.json' in manifest['hashes'], 'Unhashed application context')
        context = load(snapshot / 'application_context.json')
        require(all(not qualifies(f['attributes']) for f in context['features']),
                'Qualifying location omitted from output')
        grouped = defaultdict(list)
        eligible = defaultdict(list)
        for feature in permits['features']:
            eligible[str(feature['attributes']['TrackingNumber'])].append(feature['attributes']['OBJECTID'])
        for feature in permits['features'] + context['features']:
            grouped[str(feature['attributes']['TrackingNumber'])].append(feature['attributes']['OBJECTID'])
        require(set(grouped) == set(eligible) == set(manifest['application_group_audit']),
                'Application context group mismatch')
        for tracking, audit in manifest['application_group_audit'].items():
            require(len(grouped[tracking]) == len(set(grouped[tracking])) and
                    sorted(grouped[tracking]) == audit['complete_object_ids'] and
                    sorted(eligible[tracking]) == audit['eligible_object_ids'] and
                    audit['filtered_group_complete'] == (sorted(grouped[tracking]) == sorted(eligible[tracking])),
                    'Application context membership mismatch')
    validate_metadata(permits['metadata'], ['TrackingNumber', 'LocationID', 'ApplicationDate', 'IssueDate'])
    validate_metadata(roads['metadata'], ['SUBBLOCKKEY', 'ROADTYPE', 'FHWAFUNCTIONALCLASS'])
    for source, features in [(permits, permits['features'] + [c['feature'] for c in permits['controls']]),
                             (roads, roads['features'])]:
        required_fields = {f['name'] for f in source['metadata']['fields']
                           if f.get('type') != 'esriFieldTypeGeometry'}
        for feature in features:
            require(required_fields <= feature['attributes'].keys(), 'Source fields missing from snapshot')
    names = [f['name'] for f in permits['metadata']['fields']]
    prefix = 'enrich_'
    while any(name.startswith(prefix) for name in names):
        prefix += '_'
    index = {}
    for feature in roads['features']:
        attrs = feature['attributes']
        require(attrs['SUBBLOCKKEY'] not in index, 'Duplicate roadway key')
        index[attrs['SUBBLOCKKEY']] = attrs
    return manifest, permits, lrs, index, names, prefix


def run(snapshot, output):
    require(not (output / 'permits_enriched.csv').exists() and not (output / 'manifest.json').exists(),
            'Result already exists; use a fresh output directory')
    manifest, permits, lrs, roads, names, prefix = inputs(snapshot)
    evidence = supplemental_evidence(snapshot)
    snapshot_manifest_hash = digest(snapshot / 'manifest.json')
    records = []
    groups = defaultdict(list)
    for feature in permits['features']:
        attrs = feature['attributes']
        require(qualifies(attrs), 'Unexpected excluded input')
        require(set(attrs) <= set(names), 'Unknown source column absent from metadata')
        derived = match(feature, lrs[point_key(feature)], roads,
                        snapshot_manifest_hash == RESOLUTIONS['snapshot_manifest_sha256'])
        derived.update(class_method='nearest_road' if derived['match_status'] == 'matched' else '',
                       supporting_subblock_keys=json.dumps([derived['subblock_key']]
                           if derived['match_status'] == 'matched' else []), evidence_reference='')
        derived = supplemental.apply(feature, lrs[point_key(feature)], roads, derived, evidence)
        geometry = feature.get('geometry')
        derived.update(geometry_json=json.dumps(geometry, sort_keys=True, separators=(',', ':')),
                       geometry_x=geometry.get('x', '') if geometry else '',
                       geometry_y=geometry.get('y', '') if geometry else '', utility=ALIASES[attrs['ApplicantCompany']])
        record = {name: attrs.get(name) for name in names}
        record.update({prefix + k: v for k, v in derived.items()})
        records.append(record)
        groups[attrs['TrackingNumber']].append(record)
    for tracking, rows in groups.items():
        codes = [r[prefix+'fhwa_code'] for r in rows if r[prefix+'match_status'] == 'matched']
        highest = min(codes) if codes else ''
        complete = (len(codes) == len(rows) and not any(r.get('MultiAddresses') for r in rows)
                    and manifest.get('application_group_audit', {}).get(str(tracking), {}).get('filtered_group_complete', True))
        for row in rows:
            row.update({prefix+'highest_known_code': highest, prefix+'highest_known_name': LABELS.get(highest, ''),
                        prefix+'application_highest_code': highest if complete else '',
                        prefix+'application_highest_name': LABELS.get(highest, '') if complete else '',
                        prefix+'application_locations': len(rows), prefix+'matched_locations': len(codes),
                        prefix+'application_complete': complete})
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / 'permits_enriched.csv'
    with csv_path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=names + [prefix+x for x in DERIVED])
        writer.writeheader()
        for row in sorted(records, key=lambda r: (r['TrackingNumber'], r['LocationID'])):
            writer.writerow({k: source_cell(v) for k, v in row.items()})
    save(output / 'manifest.json', {'snapshot': str(snapshot), 'snapshot_manifest_sha256': snapshot_manifest_hash,
         'case_resolution_sha256': digest(RESOLUTION_PATH), 'case_resolution_policy': RESOLUTIONS,
         'match_policy': MATCH_POLICY,
         'supplemental_evidence_sha256': digest(snapshot / 'mar_evidence.json') if evidence else None,
         'csv_sha256': digest(csv_path), 'source_fields': names, 'enrichment_prefix': prefix,
         'locations': len(records), 'applications': len(groups),
         'match_counts': dict(Counter(r[prefix+'match_status'] for r in records)),
         'class_method_counts': dict(Counter(r[prefix+'class_method'] for r in records)),
         'exception_counts': dict(Counter(r[prefix+'match_reason'] for r in records if r[prefix+'match_status'] != 'matched'))})
    print(json.dumps(load(output / 'manifest.json'), indent=2))


def verify(snapshot, output):
    """Check raw values, membership and classes without calling the enrichment matcher."""
    manifest, source, lrs, roads, names, prefix = inputs(snapshot)
    evidence = supplemental_evidence(snapshot)
    snapshot_manifest_hash = digest(snapshot / 'manifest.json')
    report = load(output / 'manifest.json')
    require(report.get('match_policy') == MATCH_POLICY, 'Wrong match policy')
    require(report.get('supplemental_evidence_sha256') ==
            (digest(snapshot / 'mar_evidence.json') if evidence else None), 'Wrong supplemental provenance')
    require(report.get('case_resolution_sha256') == digest(RESOLUTION_PATH) and
            report.get('case_resolution_policy') == RESOLUTIONS, 'Wrong case resolution provenance')
    require(report['snapshot_manifest_sha256'] == snapshot_manifest_hash, 'Wrong snapshot manifest')
    require(report['csv_sha256'] == digest(output/'permits_enriched.csv'), 'CSV hash mismatch')
    with (output/'permits_enriched.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == names + [prefix+x for x in DERIVED], 'CSV columns missing/reordered')
        rows = list(reader)
    expected = {(str(f['attributes']['TrackingNumber']), str(f['attributes']['LocationID'])): f for f in source['features']}
    actual = {(r['TrackingNumber'], r['LocationID']): r for r in rows}
    require(len(expected) == len(source['features']) == len(rows) == len(actual), 'Duplicate/missing locations')
    require(expected.keys() == actual.keys(), 'Source membership mismatch')
    require(set(manifest['selected_applications']) == {int(k[0]) for k in expected}, 'Application selection mismatch')
    groups = defaultdict(list)
    for key, row in actual.items():
        feature = expected[key]
        attrs = feature['attributes']
        require(qualifies(attrs), 'Output includes negative-filter record')
        for name in names:
            require(row[name] == source_cell(attrs.get(name)), 'Source value changed: ' + name)
        require(json.loads(row[prefix+'geometry_json']) == feature.get('geometry'), 'Geometry changed')
        require(row[prefix+'utility'] == ALIASES[attrs['ApplicantCompany']], 'Utility mismatch')
        geometry = feature.get('geometry')
        require(row[prefix+'geometry_x'] == source_cell(geometry.get('x', '') if geometry else '') and
                row[prefix+'geometry_y'] == source_cell(geometry.get('y', '') if geometry else ''),
                'Geometry diagnostic changed')
        # Derive outcomes from input facts even for unresolved rows; never trust the CSV status.
        checked = dict.fromkeys(['subblock_key', 'road_name', 'road_type', 'distance_m',
                                 'fhwa_code', 'fhwa_name', 'resolution_id', 'resolution_basis'], '')
        checked.update(match_status='unresolved', candidate_count=0)
        response = lrs[point_key(feature)]
        if not geometry:
            reason = 'missing_geometry'
        elif 'error' in response or response.get('unavailable') or response.get('Success') is False:
            reason = 'service_error'
        else:
            require('pointOnSubBlocks' in response, 'Malformed LRS response')
            eligible = [p for p in response['pointOnSubBlocks']
                        if p.get('routeType') in {'Street', 'Service', 'Service Road', 'Ramp'}]
            checked['candidate_count'] = len(eligible)
            nearby = [p for p in eligible if isinstance(p.get('offsetInMeters'), (int, float))
                      and math.isfinite(p['offsetInMeters']) and 0 <= p['offsetInMeters'] <= 50]
            if not nearby:
                reason = 'no_eligible_road_within_50m'
            else:
                nearest = min(nearby, key=lambda p: (p['offsetInMeters'], p['subBlockKey']))
                checked.update(subblock_key=nearest['subBlockKey'], road_name=nearest.get('routeName', ''),
                               distance_m=nearest['offsetInMeters'])
                road = roads.get(nearest['subBlockKey'])
                code = road.get('FHWAFUNCTIONALCLASS') if road else None
                conflicting_names = {p.get('routeName') for p in nearby
                                     if p['offsetInMeters'] <= nearest['offsetInMeters'] + 1}
                identity = {k: attrs.get(k) for k in ('OBJECTID', 'TrackingNumber', 'LocationID')}
                exact = [p for p in nearby if p.get('unitBlock') == attrs.get('WorkLocationFullAddress')]
                address_allowed = ('BLOCK OF' in (attrs.get('WorkLocationFullAddress') or '')
                                   and len(exact) == 1 and exact[0] is nearest
                                   and nearest.get('routeType') == 'Street' and road is not None
                                   and road.get('SUBBLOCKKEY') == nearest['subBlockKey']
                                   and road.get('ROUTENAME') == nearest.get('routeName')
                                   and str(road.get('ROADTYPE')) == '1'
                                   and type(code) is int and code in LABELS)
                case_allowed = (address_allowed and snapshot_manifest_hash == RESOLUTIONS['snapshot_manifest_sha256'] and
                                identity in RESOLUTIONS['cases'] and geometry == RESOLUTIONS['geometry'] and
                                attrs.get('WorkLocationFullAddress') == RESOLUTIONS['address'] and
                                len(exact) == 1 and exact[0]['subBlockKey'] == nearest['subBlockKey'] and
                                nearest['subBlockKey'] == RESOLUTIONS['subblock_key'] and
                                nearest.get('routeType') == 'Street' and
                                nearest.get('routeName') == RESOLUTIONS['road_name'] and
                                road is not None and str(road.get('ROADTYPE')) == RESOLUTIONS['road_type'] and
                                type(code) is int and code == RESOLUTIONS['fhwa_code'])
                if len(conflicting_names) > 1 and len(exact) > 1:
                    reason = 'multiple_exact_unit_blocks'
                elif len(conflicting_names) > 1 and not (case_allowed or address_allowed):
                    reason = 'ambiguous_different_roads_within_1m'
                elif road is None:
                    reason = 'missing_subblock_lookup'
                else:
                    checked['road_type'] = road.get('ROADTYPE', '')
                    address = attrs.get('WorkLocationFullAddress') or ''
                    if road.get('SUBBLOCKKEY') != nearest['subBlockKey'] or (
                            road.get('ROUTENAME') is not None and road['ROUTENAME'] != nearest.get('routeName')):
                        reason = 'roadway_identity_disagreement'
                        checked['road_type'] = ''
                    elif str(road.get('ROADTYPE')) not in {'1', '2', '3'}:
                        reason = 'ineligible_roadway_type'
                    elif type(code) is not int or code not in LABELS:
                        reason = 'missing_or_invalid_fhwa_class'
                    elif 'BLOCK OF' in address and nearest.get('unitBlock') != address:
                        reason = 'unit_block_disagreement'
                    elif (numbered_street(address) and numbered_street(nearest.get('unitBlock') or '')
                          and numbered_street(address) != numbered_street(nearest.get('unitBlock') or '')):
                        reason = 'named_street_disagreement'
                    else:
                        reason = 'nearest_eligible_road'
                        checked.update(match_status='matched', fhwa_code=code, fhwa_name=LABELS[code])
                        if len(conflicting_names) > 1 and case_allowed:
                            reason = RESOLUTIONS['policy']
                            checked.update(resolution_id='python_oid_' + str(attrs['OBJECTID']),
                                           resolution_basis=RESOLUTIONS['evidence'])
                        elif len(conflicting_names) > 1 and address_allowed:
                            reason = ADDRESS_REASON
                            checked.update(resolution_id=MATCH_POLICY + ':oid_' + str(attrs['OBJECTID']),
                                           resolution_basis=ADDRESS_BASIS)
        checked['match_reason'] = reason
        checked.update(class_method='nearest_road' if checked['match_status'] == 'matched' else '',
                       supporting_subblock_keys=json.dumps([checked['subblock_key']]
                           if checked['match_status'] == 'matched' else []), evidence_reference='')
        checked = supplemental_verify.apply_expected(feature, response, roads, checked, evidence)
        for name, value in checked.items():
            require(row[prefix+name] == source_cell(value), 'Source-derived match mismatch: ' + name)
        groups[key[0]].append(row)
    for tracking, group in groups.items():
        require(sorted(int(r['OBJECTID']) for r in group) == manifest['whole_application_object_ids'][tracking],
                'Partial application membership')
        codes = [int(r[prefix+'fhwa_code']) for r in group if r[prefix+'match_status'] == 'matched']
        best = str(min(codes)) if codes else ''
        complete = (len(codes) == len(group) and not any(r['MultiAddresses'] for r in group)
                    and manifest.get('application_group_audit', {}).get(tracking, {}).get('filtered_group_complete', True))
        for row in group:
            require(row[prefix+'highest_known_code'] == best, 'Wrong application hierarchy')
            require(row[prefix+'highest_known_name'] == LABELS.get(int(best), '') if best else
                    row[prefix+'highest_known_name'] == '', 'Wrong highest class label')
            require(row[prefix+'application_complete'] == str(complete), 'Untruthful completeness')
            require(row[prefix+'application_highest_code'] == (best if complete else ''),
                    'Uncertified application hierarchy')
            require(row[prefix+'application_highest_name'] == (LABELS.get(int(best), '') if complete and best else ''),
                    'Uncertified application class label')
            require(row[prefix+'application_locations'] == str(len(group)), 'Wrong group size')
            require(row[prefix+'matched_locations'] == str(len(codes)), 'Wrong matched count')
    for control in source['controls']:
        require(not qualifies(control['feature']['attributes']), 'Negative control qualifies')
        require(str(control['feature']['attributes']['OBJECTID']) not in {r['OBJECTID'] for r in rows}, 'Control leaked into CSV')
    require(report['locations'] == len(rows) and report['applications'] == len(groups), 'Manifest counts wrong')
    require(report['match_counts'] == dict(Counter(r[prefix+'match_status'] for r in rows)), 'Manifest match counts wrong')
    require(report.get('class_method_counts') == dict(Counter(r[prefix+'class_method'] for r in rows)),
            'Manifest class method counts wrong')
    require(report['exception_counts'] == dict(Counter(r[prefix+'match_reason'] for r in rows
            if r[prefix+'match_status'] != 'matched')), 'Manifest exception counts wrong')
    print(f'VERIFIED: {len(rows)} locations, {len(groups)} whole applications, {len(names)} original fields, {len(source["controls"])} excluded controls')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['fetch', 'run', 'verify'])
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    snapshot = checked_path(args.snapshot)
    if args.command == 'fetch':
        fetch(snapshot)
    else:
        require(args.output, '--output required for run/verify')
        output = checked_path(args.output)
        require(output != snapshot and snapshot not in output.parents and output not in snapshot.parents,
                'Snapshot and output directories must be separate')
        (run if args.command == 'run' else verify)(snapshot, output)


if __name__ == '__main__':
    main()
