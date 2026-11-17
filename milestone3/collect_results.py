"""Publish small, reviewable SF1/SF10 evidence and a scaling table for the team."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import shutil

from manage import ROOT, save, docker


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sf1-run', type=Path, required=True)
    parser.add_argument('--sf10-run', type=Path, required=True)
    parser.add_argument('--validation-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'results')
    parser.add_argument('--host-info', type=Path, help='Optional reviewed hardware JSON with no personal identifiers')
    args = parser.parse_args()
    validation = load(args.validation_dir/'validation.json')
    if validation['status'] != 'PASS':
        raise RuntimeError('SF10 correctness validation has not passed')
    runs = {1: args.sf1_run, 10: args.sf10_run}
    manifests = {sf: load(path/'manifest.json') for sf, path in runs.items()}
    if manifests[1]['protocol'] != manifests[10]['protocol']:
        raise RuntimeError('The SF1 and SF10 protocols differ')
    if manifests[1]['query_hashes'] != manifests[10]['query_hashes']:
        raise RuntimeError('The query files differ across scales')
    if manifests[1]['server_version'] != manifests[10]['server_version']:
        raise RuntimeError('The ClickHouse versions differ across scales')
    if manifests[1]['schema_sha256'] != manifests[10]['schema_sha256']:
        raise RuntimeError('The table schemas differ across scales')
    if manifests[1]['runner_sha256'] != manifests[10]['runner_sha256']:
        raise RuntimeError('The benchmark runner versions differ across scales')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    info = json.loads(docker('info', '--format', '{{json .}}'))
    environment = {'platform':platform.platform(), 'architecture':platform.machine(),
                   'python_version':platform.python_version(), 'processor':platform.processor(),
                   'docker':{k:info[k] for k in ['ServerVersion','OSType','Architecture','NCPU','MemTotal','KernelVersion']}}
    if args.host_info:
        environment['reviewed_host_details'] = load(args.host_info)
    save(output/'environment.json',environment)
    summaries = {}
    table_totals = {}
    for sf, path in runs.items():
        target = output/f'sf{sf}'
        target.mkdir()
        manifest = manifests[sf]
        if manifest['status'] not in ('complete', 'complete_with_failures'):
            raise RuntimeError('Benchmark did not finish: ' + str(sf))
        for filename in ['attempts.csv', 'attempts.jsonl', 'summary.json', 'schedule.json', 'tables_before.json', 'tables_after.json', 'running_containers.jsonl']:
            shutil.copyfile(path/filename,target/filename)
        for result in path.glob('query_*_output.jsonl'):
            shutil.copyfile(result,target/result.name)
        public_manifest = {k:v for k,v in manifest.items() if k != 'output'}
        public_manifest['source_run_id'] = path.name
        save(target/'manifest.json', public_manifest)
        defaults = [r for r in load(path/'server_defaults.json')
                    if r['name'] in manifest['protocol']['query_settings']]
        save(target/'session_defaults.json', defaults)
        inspection = load(path/'container.json')
        save(target/'container_limits.json', {
            'image_name': inspection['Config']['Image'], 'image_id': inspection['Image'],
            'nano_cpus': inspection['HostConfig']['NanoCpus'],
            'memory_bytes': inspection['HostConfig']['Memory'],
            'memory_swap_bytes': inspection['HostConfig']['MemorySwap'],
            'network_mode': inspection['HostConfig']['NetworkMode'],
            'dataset_sha256': (inspection['Config'].get('Labels') or {}).get('tpcds.dataset_sha256')})
        table_totals[sf] = {'rows': sum(int(r['rows']) for r in load(path/'tables_before.json')),
                            'bytes_on_disk': sum(int(r['bytes_on_disk']) for r in load(path/'tables_before.json'))}
        summaries[sf] = {int(r['query']): r for r in load(path/'summary.json')}
    evidence = output/'sf10/validation'
    evidence.mkdir()
    for p in args.validation_dir.iterdir():
        if p.is_file() and p.suffix in ('.json', '.jsonl', '.sql'):
            shutil.copyfile(p,evidence/p.name)
    rows = []
    for number in manifests[1]['protocol']['queries']:
        a,b = summaries[1][number], summaries[10][number]
        row = {'query': number, 'sf1_successful_runs': a['successful_runs'], 'sf10_successful_runs': b['successful_runs'],
               'sf1_failed_runs': a['failed_runs'], 'sf10_failed_runs': b['failed_runs']}
        for metric in ['server_duration_ms', 'query_memory_bytes', 'query_cpu_seconds', 'read_rows', 'read_bytes']:
            left,right = a.get(metric+'_median'), b.get(metric+'_median')
            row['sf1_'+metric] = left
            row['sf10_'+metric] = right
            row[metric+'_ratio'] = right/left if left else None
        row['sf1_duration_cv'] = a.get('duration_cv')
        row['sf10_duration_cv'] = b.get('duration_cv')
        rows.append(row)
    with (output/'scaling_summary.csv').open('w',newline='',encoding='utf-8') as handle:
        writer = csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    save(output/'scaling_summary.json', {'comparison':'SF10 / SF1; medians of successful measured runs',
         'scope':'data-size scalability on one node; host physical disk throughput was not measured',
         'table_totals':table_totals, 'queries':rows})
    source_hashes = {p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in output.rglob('*') if p.is_file()}
    save(output/'evidence_sha256.json', source_hashes)
    print('Collected team results:',output)


if __name__ == '__main__':
    main()
