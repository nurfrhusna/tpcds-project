"""Load existing raw .dat files from a Docker volume into a fresh ClickHouse node."""
import argparse
import datetime
import json
from pathlib import Path
import re
import time
import uuid

from manage import ROOT, PROTOCOL, docker, save

IMAGE = 'team12-tpcds-validation:1.4.1'


def raw_inventory(volume):
    docker('volume', 'inspect', volume)
    return json.loads(docker('run', '--rm', '--network', 'none', '--cpus', '4', '--memory', '1g',
                            '--mount', f'type=volume,source={volume},target=/data,readonly',
                            IMAGE, 'inventory'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-volume', required=True)
    parser.add_argument('--sf', type=int, choices=PROTOCOL['scales'], required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    name, volume = args.name, args.name + '-data'
    if name in docker('ps', '-a', '--format', '{{.Names}}').splitlines():
        raise RuntimeError('Container exists; choose a new --name')
    if volume in docker('volume', 'ls', '--format', '{{.Name}}').splitlines():
        raise RuntimeError('Destination volume exists; choose a new --name')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    evidence = ROOT / 'local' / f'prepare-sf{args.sf}-{stamp}-{uuid.uuid4().hex[:6]}'
    print('Inspecting raw data and calculating all 24 file hashes...', flush=True)
    data = raw_inventory(args.data_volume)
    scale = re.search(r'-SCALE\s+(\d+)\b', data['metadata'])
    if not scale or int(scale[1]) != args.sf or not data['metadata'].startswith('4.0.0|'):
        raise RuntimeError('Generator metadata does not match TPC-DS 4.0.0 and the requested scale')
    if args.sf == 1 and data['input_sha256'] != json.loads((ROOT/'sf1_input_sha256.json').read_text()):
        raise RuntimeError('SF1 input hashes do not match the saved dataset')
    save(evidence / 'input_manifest.json', data)
    state = {'status': 'preparing', 'container': name, 'volume': volume,
             'raw_volume': args.data_volume, 'scale_factor': args.sf,
             'dataset_sha256': data['dataset_sha256'], 'protocol': PROTOCOL}
    save(evidence / 'state.json', state)
    try:
        docker('run', '-d', '--name', name, '--network', 'none',
               '--label', 'tpcds.milestone=3', '--label', 'tpcds.role=benchmark',
               '--label', 'tpcds.dataset_sha256=' + data['dataset_sha256'],
               '--cpus', PROTOCOL['container_cpus'], '--memory', PROTOCOL['container_memory_bytes'],
               '--memory-swap', PROTOCOL['container_memory_swap_bytes'],
               '--mount', f'type=volume,source={volume},target=/var/lib/clickhouse',
               PROTOCOL['clickhouse_image'])
        deadline = time.monotonic() + 120
        while True:
            try:
                docker('exec', name, 'clickhouse-client', '--query', 'SELECT 1')
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise RuntimeError('ClickHouse did not become ready')
                time.sleep(1)
        docker('exec', name, 'clickhouse-client', '--query', 'CREATE DATABASE tpcds_test')
        docker('exec', '-i', name, 'clickhouse-client', '--database=tpcds_test', '--multiquery',
               input=(ROOT/'project-snapshot/schema/create_tables_nullable.sql').read_text(encoding='utf-8-sig'))
        counts = []
        for table, info in data['files'].items():
            print('Importing ' + table + ' (' + str(info['rows']) + ' rows)', flush=True)
            docker('run', '--rm', '--label', 'tpcds.role=loader',
                   '--network', 'container:' + name, '--cpus', '4', '--memory', '2g',
                   '--mount', f'type=volume,source={args.data_volume},target=/data,readonly',
                   IMAGE, 'load', '--table', table, capture=False)
            count = int(docker('exec', name, 'clickhouse-client', '--database=tpcds_test',
                               '--query', f'SELECT count() FROM {table}'))
            counts.append({'table': table, 'raw_rows': info['rows'], 'clickhouse_rows': count,
                           'match': count == info['rows']})
            save(evidence / 'table_counts.json', counts)
            if count != info['rows']:
                raise RuntimeError('Imported row count differs from raw data: ' + table)
        state['status'] = 'ready'
    except Exception as exc:
        state.update(status='error', error=str(exc))
        raise
    finally:
        save(evidence / 'state.json', state)
        print('Preparation evidence:', evidence, flush=True)
    print('Ready:', name, flush=True)


if __name__ == '__main__':
    main()
