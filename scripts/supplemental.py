"""Conservative class-only intersection and exact-address MAR supplements."""
import json
import math
import re

INTERSECTION_BASIS = ('Both named intersection arms are present among the nearest eligible candidates; '
                      'all tied roadway records share this FHWA class. No unique subblock is asserted.')
MAR_BASIS = ('Exact ACTIVE MAR address references this eligible subblock; address street, frozen LRS '
             'candidate within 50 m, and frozen/current roadway class agree.')
ROUTE_ROADTYPE = {'Street': '1', 'Service': '2', 'Service Road': '2', 'Ramp': '3'}
NONSTANDARD = {'RAMP', 'FROM', 'TO', 'NORTHBOUND', 'SOUTHBOUND', 'EASTBOUND', 'WESTBOUND', 'BN'}


def producer():
    # Import lazily because enrich_permits imports this module for v5 application.
    if __package__:
        from . import enrich_permits
    else:
        import enrich_permits
    return enrich_permits


def normalized_address(value):
    return ' '.join(value.upper().split()) if isinstance(value, str) else ''


def street_name(value):
    """Parse a conventional, quadrant-qualified road name without ramp/direction prose."""
    if not isinstance(value, str):
        return None
    text = normalized_address(value).replace('.', '')
    if any(word in NONSTANDARD for word in text.split()):
        return None
    return producer().numbered_street('0 ' + text)


def valid_candidates(response):
    if not isinstance(response, dict) or 'error' in response or response.get('unavailable'):
        return []
    if response.get('Success') is False or response.get('status') == 'error':
        return []
    raw = response.get('pointOnSubBlocks')
    if not isinstance(raw, list):
        return []
    candidates = [p for p in raw if isinstance(p, dict) and p.get('routeType') in ROUTE_ROADTYPE
                  and isinstance(p.get('subBlockKey'), str) and p['subBlockKey']
                  and isinstance(p.get('offsetInMeters'), (int, float))
                  and not isinstance(p['offsetInMeters'], bool)
                  and math.isfinite(p['offsetInMeters']) and 0 <= p['offsetInMeters'] <= 50]
    return sorted(candidates, key=lambda p: (p['offsetInMeters'], p['subBlockKey']))


def checked_road(candidate, roads):
    """Return a frozen roadway only when all identity, type and class fields agree."""
    road = roads.get(candidate['subBlockKey'])
    if not isinstance(road, dict):
        return None
    code = road.get('FHWAFUNCTIONALCLASS')
    labels = producer().LABELS
    if (road.get('SUBBLOCKKEY') != candidate['subBlockKey'] or
            not candidate.get('routeName') or road.get('ROUTENAME') != candidate['routeName'] or
            str(road.get('ROADTYPE')) != ROUTE_ROADTYPE[candidate['routeType']] or
            type(code) is not int or code not in labels):
        return None
    return road


def intersection(feature, response, roads, baseline):
    e = producer()
    if baseline.get('match_reason') != 'ambiguous_different_roads_within_1m':
        return None
    address = normalized_address(feature.get('attributes', {}).get('WorkLocationFullAddress'))
    arms = address.split(' AND ')
    if len(arms) != 2:
        return None
    parsed_arms = [street_name(arm) for arm in arms]
    if not all(parsed_arms) or parsed_arms[0] == parsed_arms[1]:
        return None
    candidates = valid_candidates(response)
    if not candidates:
        return None
    nearest = candidates[0]['offsetInMeters']
    tied = [p for p in candidates if p['offsetInMeters'] <= nearest + 1]
    names = {street_name(p.get('routeName')) for p in tied}
    if None in names:
        return None
    if not all(arm in names for arm in parsed_arms):
        return None
    checked = [checked_road(p, roads) for p in tied]
    if not all(checked):
        return None
    classes = {road['FHWAFUNCTIONALCLASS'] for road in checked}
    if len(classes) != 1:
        return None
    code = classes.pop()
    return {**baseline, 'match_status': 'matched', 'match_reason': 'intersection_class_consensus',
            'fhwa_code': code, 'fhwa_name': e.LABELS[code],
            'subblock_key': '', 'road_name': '', 'road_type': '', 'distance_m': '',
            'resolution_id': '', 'resolution_basis': INTERSECTION_BASIS,
            'class_method': 'intersection_consensus',
            'supporting_subblock_keys': json.dumps(sorted({p['subBlockKey'] for p in tied})),
            'evidence_reference': 'frozen_lrs_and_roads'}


def mar(feature, response, roads, baseline, evidence):
    e = producer()
    if not isinstance(evidence, dict):
        return None
    address = normalized_address(feature.get('attributes', {}).get('WorkLocationFullAddress'))
    # A door number and a conventional street/quadrant are required. Range, block,
    # intersection, exit and directional ramp descriptions cannot use this route.
    if (not re.fullmatch(r'\d+[A-Z]? [A-Z0-9 .-]+ (?:NE|NW|SE|SW)', address) or
            any(word in address.split() for word in ('AND', 'BLOCK', 'EXIT', 'RAMP')) or
            ' - ' in address):
        return None
    parsed_address = e.numbered_street(address)
    if not parsed_address:
        return None
    address_features = evidence.get('address_features')
    road_features = evidence.get('road_features')
    if not isinstance(address_features, list) or not isinstance(road_features, list):
        return None
    active = []
    for item in address_features:
        attrs = item.get('attributes') if isinstance(item, dict) else None
        if not isinstance(attrs, dict) or normalized_address(attrs.get('ADDRESS')) != address:
            continue
        # Unknown status cannot establish which matching address records are active.
        if not isinstance(attrs.get('STATUS'), str) or not attrs['STATUS'].strip():
            return None
        if attrs['STATUS'] == 'ACTIVE':
            active.append(attrs)
    keys = {a.get('SUBBLOCKKEY') for a in active}
    if not active or len(keys) != 1 or not all(isinstance(k, str) and k.strip() for k in keys):
        return None
    key = next(iter(keys))
    current = [item['attributes'] for item in road_features
               if isinstance(item, dict) and isinstance(item.get('attributes'), dict)
               and item['attributes'].get('SUBBLOCKKEY') == key]
    if len(current) != 1:
        return None
    live = current[0]
    frozen = roads.get(key)
    if not isinstance(frozen, dict):
        return None
    code = frozen.get('FHWAFUNCTIONALCLASS')
    if (frozen.get('SUBBLOCKKEY') != key or live.get('SUBBLOCKKEY') != key or
            str(frozen.get('ROADTYPE')) not in {'1', '2', '3'} or
            str(live.get('ROADTYPE')) != str(frozen.get('ROADTYPE')) or
            frozen.get('ROUTENAME') != live.get('ROUTENAME') or
            type(code) is not int or code not in e.LABELS or
            type(live.get('FHWAFUNCTIONALCLASS')) is not int or live['FHWAFUNCTIONALCLASS'] != code or
            street_name(frozen.get('ROUTENAME')) != parsed_address):
        return None
    candidates = [p for p in valid_candidates(response) if p['subBlockKey'] == key]
    if not candidates or any(checked_road(p, roads) != frozen for p in candidates):
        return None
    chosen = candidates[0]
    return {**baseline, 'match_status': 'matched', 'match_reason': 'mar_exact_address',
            'fhwa_code': code, 'fhwa_name': e.LABELS[code],
            'subblock_key': key, 'road_name': frozen['ROUTENAME'],
            'road_type': frozen['ROADTYPE'], 'distance_m': chosen['offsetInMeters'],
            'resolution_id': '', 'resolution_basis': MAR_BASIS,
            'class_method': 'mar_address', 'supporting_subblock_keys': json.dumps([key]),
            'evidence_reference': 'mar_evidence.json'}


def apply(feature, response, frozen_roads, baseline_result, evidence):
    """Return a new result; leave baseline, raw responses and evidence untouched."""
    baseline = dict(baseline_result)
    if baseline.get('match_status') == 'matched' or not feature.get('geometry'):
        return baseline
    if baseline.get('match_reason') in {'service_error', 'missing_geometry'}:
        return baseline
    return (intersection(feature, response, frozen_roads, baseline) or
            mar(feature, response, frozen_roads, baseline, evidence) or baseline)
