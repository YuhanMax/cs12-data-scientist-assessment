"""Attach retained MAR evidence to a new copy of a frozen permit snapshot."""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from . import enrich_permits as e
else:
    import enrich_permits as e


def normalized(value):
    return ' '.join((value or '').upper().split())


def capture(snapshot, output, saved_queries=None):
    e.require((snapshot / '.fetch_complete').is_file(), 'Input snapshot is not finalized')
    e.require(not (snapshot / 'mar_evidence.json').exists(),
              'Input already has MAR evidence; start from the original frozen snapshot')
    e.require(not output.exists() and snapshot != output and snapshot not in output.parents
              and output not in snapshot.parents, 'Use a new, separate snapshot directory')
    _, permits, lrs, roads, _, _ = e.inputs(snapshot)
    addresses = set()
    for feature in permits['features']:
        baseline = e.match(feature, lrs[e.point_key(feature)], roads, False)
        address = normalized(feature['attributes'].get('WorkLocationFullAddress'))
        if (baseline['match_status'] != 'matched' and ' AND ' not in address
                and 'BLOCK OF' not in address and e.numbered_street(address)):
            addresses.add(address)
    queries = []
    if saved_queries is not None:
        paths = sorted(Path(saved_queries).glob('mar_addresses_*.json'))
        paths += sorted(Path(saved_queries).glob('mar_roads_*.json'))
        e.require(paths, 'No saved MAR queries found')
        queries = [e.load(path) for path in paths]
        e.require(all('response' in record for record in queries), 'Saved MAR query failed')
    else:
        def retrieve(url, where, fields):
            params = {'where': where, 'outFields': fields, 'returnGeometry': 'true', 'outSR': 4326}
            with e.client() as session:
                value = e.api(session, url, **params)
            e.require(not value.get('exceededTransferLimit'), 'Truncated MAR evidence query')
            queries.append({'url': url, 'params': params,
                            'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'response': value})
            return value['features']

        def literals(values):
            return ','.join("'" + value.replace("'", "''") + "'" for value in values)

        keys = set()
        selected = sorted(addresses)
        for offset in range(0, len(selected), 20):
            records = retrieve(e.MAR + '/query', 'UPPER(ADDRESS) IN (' +
                               literals(selected[offset:offset + 20]) + ')',
                               'OBJECTID,MAR_ID,ADDRESS,STATUS,SUBBLOCKKEY,ROUTEID')
            keys.update(f['attributes']['SUBBLOCKKEY'] for f in records
                        if f['attributes'].get('SUBBLOCKKEY'))
        selected = sorted(keys)
        for offset in range(0, len(selected), 50):
            retrieve(e.ROADS + '/query', 'SUBBLOCKKEY IN (' + literals(selected[offset:offset + 50]) + ')',
                     'OBJECTID,SUBBLOCKKEY,ROADTYPE,FHWAFUNCTIONALCLASS,ROUTENAME')
    source_urls = {e.MAR + '/query', e.ROADS + '/query'}
    e.require(queries and all(record.get('url') in source_urls for record in queries),
              'Unexpected or empty MAR query evidence')
    evidence = {'source_url': e.MAR, 'road_source_url': e.ROADS,
                'base_snapshot_sha256': e.digest(snapshot / 'manifest.json'), 'queries': queries,
                'address_features': [f for q in queries if q['url'] == e.MAR + '/query'
                                     for f in q['response']['features']],
                'road_features': [f for q in queries if q['url'] == e.ROADS + '/query'
                                  for f in q['response']['features']]}
    shutil.copytree(snapshot, output, ignore=shutil.ignore_patterns('.fetch_complete'))
    (output / 'base_manifest.json').write_bytes((snapshot / 'manifest.json').read_bytes())
    e.save(output / 'mar_evidence.json', evidence)
    manifest = e.load(snapshot / 'manifest.json')
    manifest['hashes'].update({name: e.digest(output / name)
                              for name in ('base_manifest.json', 'mar_evidence.json')})
    manifest['supplemental_policy'] = e.MATCH_POLICY
    manifest['supplemental_attached_utc'] = datetime.now(timezone.utc).isoformat()
    e.save(output / 'manifest.json', manifest)
    e.supplemental_evidence(output)
    (output / '.fetch_complete').touch()
    print(json.dumps({'snapshot': str(output), 'eligible_query_addresses': len(addresses),
                      'address_records': len(evidence['address_features']),
                      'road_records': len(evidence['road_features']),
                      'base_snapshot_sha256': evidence['base_snapshot_sha256']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', required=True, help='New child directory of artifacts')
    parser.add_argument('--saved-queries', type=Path, help='Reuse retained mar_addresses/roads JSON responses')
    args = parser.parse_args()
    capture(e.checked_path(args.snapshot), e.checked_path(args.output), args.saved_queries)
