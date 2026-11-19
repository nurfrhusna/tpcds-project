"""Collect evidence and compare SF10 and, when provided, SF100 with SF1."""
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
    parser.add_argument('--sf100-run', type=Path)
    parser.add_argument('--validation-dir', type=Path, required=True, help='SF10 validation directory')
    parser.add_argument('--sf100-validation-dir', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'results')
    parser.add_argument('--host-info', type=Path, help='Optional reviewed hardware JSON with no personal identifiers')
    args = parser.parse_args()
    if bool(args.sf100_run) != bool(args.sf100_validation_dir):
        parser.error('--sf100-run and --sf100-validation-dir must be supplied together')
    runs = {1: args.sf1_run, 10: args.sf10_run}
    validation_dirs = {10: args.validation_dir}
    if args.sf100_run:
        runs[100] = args.sf100_run
        validation_dirs[100] = args.sf100_validation_dir
    manifests = {sf: load(path/'manifest.json') for sf, path in runs.items()}
    inspections = {sf: load(path/'container.json') for sf, path in runs.items()}
    baseline = manifests[1]
    for sf, manifest in manifests.items():
        if manifest['scale_factor'] != sf or manifest['status'] not in ('complete', 'complete_with_failures'):
            raise RuntimeError(f'Expected a finished SF{sf} benchmark')
        for key in ('protocol', 'query_hashes', 'schema_sha256', 'runner_sha256', 'server_version'):
            if manifest[key] != baseline[key]:
                raise RuntimeError(f'SF{sf} and SF1 differ in {key}')
        if manifest.get('environment') != baseline.get('environment'):
            raise RuntimeError(f'SF{sf} and SF1 differ in Docker engine or environment')
        if inspections[sf]['Image'] != inspections[1]['Image']:
            raise RuntimeError(f'SF{sf} and SF1 use different ClickHouse images')
    if args.sf100_run and not baseline.get('environment'):
        raise RuntimeError('Three-scale collection requires Docker environment evidence from each run')
    for sf, directory in validation_dirs.items():
        path = directory/'validation.json'
        validation = load(path)
        if (validation['status'] != 'PASS' or validation['scale_factor'] != sf or
                validation['dataset_sha256'] != manifests[sf]['dataset_sha256'] or
                hashlib.sha256(path.read_bytes()).hexdigest() != manifests[sf]['validation_sha256']):
            raise RuntimeError(f'The SF{sf} validation report must match the one used for timing')
    if baseline.get('environment'):
        docker_environment = baseline['environment']['docker']
    else:  # Keep collection compatible with the saved, earlier two-scale runs.
        info = json.loads(docker('info', '--format', '{{json .}}'))
        docker_environment = {k:info[k] for k in ['ServerVersion','OSType','Architecture','NCPU','MemTotal','KernelVersion']}
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = {'platform':platform.platform(), 'architecture':platform.machine(),
                   'python_version':platform.python_version(), 'processor':platform.processor(),
                   'docker':docker_environment}
    if args.host_info:
        environment['reviewed_host_details'] = load(args.host_info)
    save(output/'environment.json',environment)
    summaries = {}
    table_totals = {}
    for sf, path in runs.items():
        target = output/f'sf{sf}'
        target.mkdir()
        manifest = manifests[sf]
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
        inspection = inspections[sf]
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
    for sf, directory in validation_dirs.items():
        evidence = output/f'sf{sf}/validation'
        evidence.mkdir()
        for p in directory.iterdir():
            if p.is_file() and p.suffix in ('.json', '.jsonl', '.sql'):
                shutil.copyfile(p,evidence/p.name)
    rows = []
    for number in manifests[1]['protocol']['queries']:
        a,b = summaries[1][number], summaries[10][number]
        row = {'query': number, 'sf1_successful_runs': a['successful_runs'], 'sf10_successful_runs': b['successful_runs'],
               'sf1_failed_runs': a['failed_runs'], 'sf10_failed_runs': b['failed_runs']}
        metrics = ['server_duration_ms', 'query_memory_bytes', 'query_cpu_seconds', 'read_rows', 'read_bytes']
        for metric in metrics:
            left,right = a.get(metric+'_median'), b.get(metric+'_median')
            row['sf1_'+metric] = left
            row['sf10_'+metric] = right
            row[metric+'_ratio'] = right/left if left and right is not None else None
        row['sf1_duration_cv'] = a.get('duration_cv')
        row['sf10_duration_cv'] = b.get('duration_cv')
        if 100 in summaries:
            c = summaries[100][number]
            row['sf100_successful_runs'] = c['successful_runs']
            row['sf100_failed_runs'] = c['failed_runs']
            row['sf100_duration_cv'] = c.get('duration_cv')
            for metric in metrics:
                base = row['sf1_'+metric]
                large = c.get(metric+'_median')
                row['sf100_'+metric] = large
                row[metric+'_sf100_over_sf1'] = large/base if base and large is not None else None
        rows.append(row)
    with (output/'scaling_summary.csv').open('w',newline='',encoding='utf-8') as handle:
        writer = csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    comparison = 'SF10 / SF1 and SF100 / SF1' if 100 in summaries else 'SF10 / SF1'
    save(output/'scaling_summary.json', {'comparison':comparison+'; medians of successful measured runs',
         'scope':'data-size scalability on one node; host physical disk throughput was not measured',
         'table_totals':table_totals, 'queries':rows})
    source_hashes = {p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in output.rglob('*') if p.is_file()}
    save(output/'evidence_sha256.json', source_hashes)
    print('Collected team results:',output)


if __name__ == '__main__':
    main()
