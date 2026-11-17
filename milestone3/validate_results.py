"""Compare ClickHouse and canonical DuckDB SQL on identical raw TPC-DS files."""
import argparse
import datetime
import decimal
import hashlib
import json
from pathlib import Path
import re
import uuid

from manage import ROOT, PROTOCOL, docker, save
from prepare_volume import IMAGE, raw_inventory
from run_controlled import client, decode_rows, json_rows, query
from validation_helpers import compare_bags, rows_equal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-volume', required=True)
    parser.add_argument('--container', required=True)
    parser.add_argument('--sf', type=int, choices=[1, 10], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stop-clickhouse-during-reference', action='store_true',
                        help='Temporarily stop and restart this experiment container to free RAM')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'scale_factor': args.sf, 'clickhouse_container': args.container,
              'raw_volume': args.data_volume, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'comparison_policy': {'exact': 'integers and decimals', 'float_relative_tolerance': 1e-9,
                                    'float_absolute_tolerance': 1e-8, 'duplicates': 'consume each matching occurrence once'},
              'query_hashes': {}, 'queries': []}
    save(output / 'validation.json', report)
    stopped = False
    try:
        inspection = json.loads(docker('inspect', args.container))[0]
        labels = inspection['Config'].get('Labels') or {}
        if labels.get('tpcds.role') != 'benchmark' or labels.get('tpcds.milestone') != '3':
            raise RuntimeError('Expected a Milestone 3 benchmark container')
        data = raw_inventory(args.data_volume)
        scale = re.search(r'-SCALE\s+(\d+)\b', data['metadata'])
        if not scale or int(scale[1]) != args.sf:
            raise RuntimeError('Raw generator metadata does not match the requested scale')
        if labels.get('tpcds.dataset_sha256') != data['dataset_sha256']:
            raise RuntimeError('Container input fingerprint differs from the reference input files')
        report['dataset_sha256'] = data['dataset_sha256']
        report['server_version'] = query(args.container, 'SELECT version()')
        report['validation_image_id'] = json.loads(docker('image', 'inspect', IMAGE))[0]['Id']
        report['canonical_sql_hashes'] = {str(n): hashlib.sha256((ROOT/f'validation/canonical-queries/query_{n:02}.sql').read_bytes()).hexdigest() for n in PROTOCOL['queries']}
        report['reference_schema_sha256'] = hashlib.sha256((ROOT/'validation/schema.json').read_bytes()).hexdigest()
        save(output / 'input_manifest.json', data)
        counts = []
        for table, info in data['files'].items():
            count = int(query(args.container, f'SELECT count() FROM {table}'))
            if count != info['rows']:
                raise RuntimeError('ClickHouse row count differs from raw data: ' + table)
            counts.append({'table': table, 'raw_rows': info['rows'], 'clickhouse_rows': count})
        save(output / 'table_counts.json', counts)
        for number in PROTOCOL['queries']:
            print('Collecting ClickHouse Q' + str(number), flush=True)
            path = ROOT / f'project-snapshot/queries/query_{number:02}.sql'
            report['query_hashes'][str(number)] = hashlib.sha256(path.read_bytes()).hexdigest()
            sql = path.read_text(encoding='utf-8-sig').strip().rstrip(';')
            result = client(args.container, sql + ' FORMAT JSONCompactEachRow',
                            settings=PROTOCOL['query_settings'], query_id='m3_validation_' + uuid.uuid4().hex,
                            timeout=PROTOCOL['query_settings']['max_execution_time'] + 30)
            if result.returncode:
                raise RuntimeError(result.stderr)
            (output/f'query_{number:02}_clickhouse.jsonl').write_text(result.stdout, encoding='utf-8')
        if args.stop_clickhouse_during_reference:
            docker('stop', '--timeout', '10', args.container)
            stopped = True
        reference_volume = 'team12-reference-sf' + str(args.sf) + '-' + uuid.uuid4().hex[:10]
        report['reference_volume'] = reference_volume
        save(output / 'validation.json', report)
        docker('run', '--rm', '--label', 'tpcds.role=reference', '--network', 'none',
               '--cpus', '4', '--memory', '6g', '--memory-swap', '6g',
               '--mount', f'type=volume,source={args.data_volume},target=/data,readonly',
               '--mount', f'type=volume,source={reference_volume},target=/reference',
               '--mount', f'type=bind,source={output},target=/evidence', IMAGE, 'reference', capture=False)
        reference_report = json.loads((output/'reference_report.json').read_text())
        if reference_report['status'] != 'PASS' or reference_report['dataset_sha256'] != report['dataset_sha256']:
            raise RuntimeError('Independent reference or input-fingerprint validation failed')
        report['reference_engine'] = reference_report['reference_engine']
        report['reference_version'] = reference_report['reference_version']
        ref_counts = {r['table']: r['reference_rows'] for r in json.loads((output/'reference_table_counts.json').read_text())}
        for row in counts:
            row['reference_rows'] = ref_counts[row['table']]
            row['match'] = row['raw_rows'] == row['clickhouse_rows'] == row['reference_rows']
        save(output/'table_counts.json', counts)
        report['all_24_table_counts_match'] = len(counts) == 24 and all(r['match'] for r in counts)
        for entry in reference_report['queries']:
            number = entry['query']
            if entry['query_sha256'] != report['query_hashes'][str(number)]:
                raise RuntimeError('The validation image contains different SQL; rebuild it')
            reference = json.loads((output/f'query_{number:02}_reference.json').read_text(), parse_float=decimal.Decimal)
            expected = decode_rows(reference['rows'], reference['columns'])
            raw = [json.loads(line, parse_float=decimal.Decimal) for line in (output/f'query_{number:02}_clickhouse.jsonl').read_text().splitlines() if line.strip()]
            observed = decode_rows(raw, reference['columns'])
            comparison = compare_bags(expected, observed)
            report['queries'].append({'query': number, 'reference_rows': len(expected), 'clickhouse_rows': len(observed),
                                      'comparison': comparison, 'project_vs_canonical': entry['project_vs_canonical'],
                                      'ordered_result_equal': len(expected) == len(observed) and all(rows_equal(a,b) for a,b in zip(expected,observed)),
                                      'dialect_changes': entry['dialect_changes']})
            print('Q' + str(number) + ': ' + str(comparison), flush=True)
        report['status'] = 'PASS' if report['all_24_table_counts_match'] and all(q['comparison']['equal'] and q['project_vs_canonical']['equal'] for q in report['queries']) else 'FAIL'
    except Exception as exc:
        report.update(status='ERROR', error=str(exc))
        raise
    finally:
        if stopped:
            docker('start', args.container)
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save(output/'validation.json', report)
        print('Validation evidence:', output, flush=True)
    if report['status'] != 'PASS':
        raise RuntimeError('Query validation failed; do not benchmark until resolved')


if __name__ == '__main__':
    main()
