"""Independently derive the two v5 supplemental outcomes from retained evidence.

This module intentionally does not call the production matcher or its supplemental
decision code. A missing or inconsistent fact leaves the baseline result unchanged.
"""

import json
import math
import re


LABELS = {1: 'Interstate', 2: 'Principal Arterial - Other Freeways or Expressways',
          3: 'Principal Arterial - Other', 4: 'Minor Arterial',
          5: 'Major Collector', 6: 'Minor Collector', 7: 'Local'}
ROUTE_TYPES = {'Street': '1', 'Service': '2', 'Service Road': '2', 'Ramp': '3'}
SUFFIXES = {'ST': 'STREET', 'STREET': 'STREET', 'AVE': 'AVENUE', 'AVENUE': 'AVENUE',
            'RD': 'ROAD', 'ROAD': 'ROAD', 'DR': 'DRIVE', 'DRIVE': 'DRIVE',
            'PL': 'PLACE', 'PLACE': 'PLACE', 'CT': 'COURT', 'COURT': 'COURT',
            'BLVD': 'BOULEVARD', 'BOULEVARD': 'BOULEVARD',
            'TER': 'TERRACE', 'TERRACE': 'TERRACE', 'CIR': 'CIRCLE',
            'CIRCLE': 'CIRCLE', 'PKWY': 'PARKWAY', 'PARKWAY': 'PARKWAY',
            'LN': 'LANE', 'LANE': 'LANE', 'WAY': 'WAY'}
NONSTANDARD = {'BN', 'RAMP', 'EXIT', 'FROM', 'TO', 'NORTHBOUND', 'SOUTHBOUND',
               'EASTBOUND', 'WESTBOUND', 'BOUNDARY'}
INTERSECTION_BASIS = ('Both named intersection arms are present among the nearest eligible '
                      'candidates; all tied roadway records share this FHWA class. No unique '
                      'subblock is asserted.')
MAR_BASIS = ('Exact ACTIVE MAR address references this eligible subblock; address street, '
             'frozen LRS candidate within 50 m, and frozen/current roadway class agree.')


def _text(value):
    return ' '.join(value.upper().split()) if isinstance(value, str) else ''


def _street(value):
    """Conservative street identity, including quadrant; accepts standard DC suffixes."""
    words = _text(value).replace('.', '').split()
    if len(words) < 3 or words[-1] not in {'NE', 'NW', 'SE', 'SW'}:
        return None
    suffix = SUFFIXES.get(words[-2])
    name = words[:-2]
    if not suffix or not name or any(not re.fullmatch(r'[A-Z0-9]+', part) for part in name):
        return None
    if any(part in NONSTANDARD for part in name):
        return None
    return tuple(name), suffix, words[-1]


def _numbered_address(value):
    text = _text(value)
    if ' AND ' in text or 'BLOCK OF' in text:
        return None
    match = re.fullmatch(r'\d+[A-Z]? (.+)', text)
    return _street(match.group(1)) if match else None


def _intersection(value):
    text = _text(value)
    if text.count(' AND ') != 1 or 'BN' in text.split() or 'RAMP' in text.split():
        return None
    arms = [_street(part) for part in text.split(' AND ')]
    return frozenset(arms) if all(arms) and arms[0] != arms[1] else None


def _candidate_rows(response):
    if not isinstance(response, dict):
        return []
    raw = response.get('pointOnSubBlocks')
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict) or item.get('routeType') not in ROUTE_TYPES:
            continue
        distance = item.get('offsetInMeters')
        key = item.get('subBlockKey')
        if (type(distance) not in (int, float) or not math.isfinite(distance)
                or not 0 <= distance <= 50 or not isinstance(key, str) or not key.strip()):
            continue
        rows.append(item)
    return sorted(rows, key=lambda row: (row['offsetInMeters'], row['subBlockKey']))


def _attrs(value):
    if not isinstance(value, dict):
        return None
    return value.get('attributes') if isinstance(value.get('attributes'), dict) else value


def _verified_road(candidate, frozen_roads):
    key = candidate['subBlockKey']
    road = _attrs(frozen_roads.get(key)) if isinstance(frozen_roads, dict) else None
    if not isinstance(road, dict) or road.get('SUBBLOCKKEY') != key:
        return None
    if str(road.get('ROADTYPE')) != ROUTE_TYPES[candidate['routeType']]:
        return None
    if (not candidate.get('routeName') or
            road.get('ROUTENAME') != candidate.get('routeName') or
            _street(road.get('ROUTENAME')) is None):
        return None
    code = road.get('FHWAFUNCTIONALCLASS')
    return road if type(code) is int and code in LABELS else None


def _intersection_expected(address, candidates, frozen_roads, baseline):
    arms = _intersection(address)
    if (baseline.get('match_reason') != 'ambiguous_different_roads_within_1m'
            or not arms or not candidates):
        return baseline
    nearest = candidates[0]['offsetInMeters']
    near = [row for row in candidates if row['offsetInMeters'] <= nearest + 1]
    road_names = set()
    codes = set()
    keys = set()
    for row in near:
        road = _verified_road(row, frozen_roads)
        if road is None:
            return baseline
        road_names.add(_street(row.get('routeName')))
        codes.add(road['FHWAFUNCTIONALCLASS'])
        keys.add(row['subBlockKey'])
    if not arms <= road_names or len(codes) != 1:
        return baseline
    code = next(iter(codes))
    result = dict(baseline)
    result.update(match_status='matched', match_reason='intersection_class_consensus',
                  subblock_key='', road_name='', road_type='', distance_m='',
                  fhwa_code=code, fhwa_name=LABELS[code], resolution_id='',
                  resolution_basis=INTERSECTION_BASIS, class_method='intersection_consensus',
                  supporting_subblock_keys=json.dumps(sorted(keys)),
                  evidence_reference='frozen_lrs_and_roads')
    return result


def _mar_expected(address, candidates, frozen_roads, baseline, evidence):
    source_street = _numbered_address(address)
    if source_street is None or not isinstance(evidence, dict):
        return baseline
    address_features = evidence.get('address_features')
    road_features = evidence.get('road_features')
    if not isinstance(address_features, list) or not isinstance(road_features, list):
        return baseline
    active = []
    for item in address_features:
        attrs = _attrs(item)
        if (isinstance(attrs, dict) and _text(attrs.get('ADDRESS')) == _text(address)
                and attrs.get('STATUS') == 'ACTIVE'):
            active.append(attrs)
    if not active:
        return baseline
    keys = {row.get('SUBBLOCKKEY') for row in active}
    if len(keys) != 1 or not all(isinstance(key, str) and key.strip() for key in keys):
        return baseline
    key = next(iter(keys))
    matches = [(_attrs(item)) for item in road_features]
    matches = [row for row in matches if isinstance(row, dict) and row.get('SUBBLOCKKEY') == key]
    if len(matches) != 1:
        return baseline
    current = matches[0]
    current_code = current.get('FHWAFUNCTIONALCLASS')
    if (str(current.get('ROADTYPE')) not in {'1', '2', '3'} or
            type(current_code) is not int or current_code not in LABELS or
            _street(current.get('ROUTENAME')) != source_street):
        return baseline
    candidates_for_key = [row for row in candidates if row['subBlockKey'] == key]
    if not candidates_for_key:
        return baseline
    selected = candidates_for_key[0]
    frozen = _verified_road(selected, frozen_roads)
    if (frozen is None or _street(selected.get('routeName')) != source_street or
            frozen.get('ROUTENAME') != current.get('ROUTENAME') or
            str(frozen['ROADTYPE']) != str(current['ROADTYPE']) or
            frozen['FHWAFUNCTIONALCLASS'] != current_code):
        return baseline
    if any(_verified_road(row, frozen_roads) != frozen for row in candidates_for_key):
        return baseline
    result = dict(baseline)
    result.update(match_status='matched', match_reason='mar_exact_address',
                  subblock_key=key, road_name=frozen['ROUTENAME'],
                  road_type=frozen['ROADTYPE'], distance_m=selected['offsetInMeters'],
                  fhwa_code=current_code, fhwa_name=LABELS[current_code],
                  resolution_id='', resolution_basis=MAR_BASIS,
                  class_method='mar_address', supporting_subblock_keys=json.dumps([key]),
                  evidence_reference='mar_evidence.json')
    return result


def apply_expected(feature, response, frozen_roads, baseline_expected, evidence):
    """Return the independently verified expected row, preserving baseline on doubt."""
    result = dict(baseline_expected)
    if (result.get('match_status') != 'unresolved' or not feature.get('geometry')
            or result.get('match_reason') in {'service_error', 'missing_geometry'}):
        return result
    if (not isinstance(response, dict) or 'error' in response or
            response.get('status') == 'error' or response.get('unavailable') or
            response.get('Success') is False):
        return result
    candidates = _candidate_rows(response)
    address = feature.get('attributes', {}).get('WorkLocationFullAddress') or ''
    if _intersection(address):
        return _intersection_expected(address, candidates, frozen_roads, result)
    return _mar_expected(address, candidates, frozen_roads, result, evidence)
