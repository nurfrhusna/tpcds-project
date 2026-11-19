"""Read-only raw-data utilities and an independent, same-input DuckDB reference."""
import argparse
import datetime
import decimal
import hashlib
import http.client
import json
from pathlib import Path
import sys
import time
import urllib.parse

from original_importer import converted_chunks
from sql_dialect import portable_sql
from validation_helpers import compare_bags, rows_equal

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / "schema.json").read_text())
QUERIES = (3, 7, 31, 47, 64, 82)


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


def inventory():
    files = {p.stem: p for p in Path('/data').glob('*.dat') if p.stem != 'dbgen_version'}
    if set(files) != set(SCHEMA):
        raise RuntimeError("Expected the 24 TPC-DS data files")
    result = {}
    for table, path in sorted(files.items()):
        digest = hashlib.sha256()
        count = 0
        last = b''
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
                count += chunk.count(b'\n')
                last = chunk[-1:]
        if path.stat().st_size and last != b'\n':
            raise RuntimeError("Data file lacks a final newline: " + table)
        result[table] = {'sha256': digest.hexdigest(), 'rows': count, 'bytes': path.stat().st_size}
    hashes = {k: v['sha256'] for k, v in result.items()}
    return {'files': result, 'input_sha256': hashes,
            'dataset_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
            'metadata': Path('/data/dbgen_version.dat').read_text().strip()}


def reference(memory_limit_gb):
    import duckdb
    evidence = Path('/evidence')
    evidence.mkdir(exist_ok=True)
    report = {'status': 'RUNNING', 'reference_engine': 'DuckDB', 'reference_version': duckdb.__version__,
              'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'queries': []}
    save(evidence / 'reference_report.json', report)
    connection = None
    try:
        data = inventory()
        report['dataset_sha256'] = data['dataset_sha256']
        save(evidence / 'input_manifest.json', data)
        database = Path('/reference/same_input.duckdb')
        if database.exists():
            raise RuntimeError("Reference database already exists; use a fresh reference volume")
        connection = duckdb.connect(str(database))
        connection.execute("SET memory_limit = ?", [f'{memory_limit_gb}GB'])
        connection.execute('SET threads=4')
        connection.execute("SET temp_directory='/reference/temp'")
        # CSV input order is immaterial to the reference queries. Avoid retaining
        # it while importing tables that are much larger than available memory.
        connection.execute('SET preserve_insertion_order=false')
        counts = []
        for table, fields in sorted(SCHEMA.items()):
            print('DuckDB loading ' + table, file=sys.stderr, flush=True)
            columns = dict(fields, __trailing_pipe='VARCHAR')
            connection.execute(f'''CREATE TABLE "{table}" AS
                SELECT * EXCLUDE (__trailing_pipe) FROM read_csv(?, columns=?,
                delim='|', header=false, quote='', escape='', nullstr='', auto_detect=false)''',
                [f'/data/{table}.dat', columns])
            count = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            if count != data['files'][table]['rows']:
                raise RuntimeError('Reference row count mismatch: ' + table)
            counts.append({'table': table, 'reference_rows': count})
        save(evidence / 'reference_table_counts.json', counts)
        connection.execute('SET preserve_insertion_order=true')
        for number in QUERIES:
            print('DuckDB checking Q' + str(number), file=sys.stderr, flush=True)
            source = (ROOT / f'queries/query_{number:02}.sql').read_text(encoding='utf-8-sig')
            portable, changes = portable_sql(number, source)
            (evidence / f'query_{number:02}_portable.sql').write_text(portable)
            started = time.perf_counter()
            cursor = connection.execute(portable)
            columns = [{'name': c[0], 'type': str(c[1])} for c in cursor.description]
            rows = cursor.fetchall()
            seconds = time.perf_counter() - started
            canonical = (ROOT / f'canonical-queries/query_{number:02}.sql').read_text()
            canonical_rows = connection.execute(canonical).fetchall()
            comparison = compare_bags(rows, canonical_rows)
            record = {'query': number, 'query_sha256': hashlib.sha256((ROOT / f'queries/query_{number:02}.sql').read_bytes()).hexdigest(),
                      'project_rows': len(rows), 'canonical_rows': len(canonical_rows),
                      'project_vs_canonical': comparison, 'dialect_changes': changes,
                      'reference_execution_seconds': round(seconds, 6)}
            save(evidence / f'query_{number:02}_reference.json', {'columns': columns, 'rows': rows})
            save(evidence / f'query_{number:02}_canonical.json', {'columns': columns, 'rows': canonical_rows})
            report['queries'].append(record)
            save(evidence / 'reference_report.json', report)
        report['status'] = 'PASS' if all(q['project_vs_canonical']['equal'] for q in report['queries']) else 'FAIL'
    except Exception as exc:
        report.update(status='ERROR', error=str(exc))
        raise
    finally:
        if connection:
            connection.close()
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save(evidence / 'reference_report.json', report)
    if report['status'] != 'PASS':
        raise RuntimeError('Project SQL differs from canonical SQL; inspect reference_report.json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['inventory', 'convert', 'load', 'reference'])
    parser.add_argument('--table', choices=sorted(SCHEMA))
    parser.add_argument('--memory-limit-gb', type=int, choices=[4, 7], default=4)
    args = parser.parse_args()
    if args.command == 'inventory':
        print(json.dumps(inventory()))
    elif args.command in ('convert', 'load'):
        if not args.table:
            parser.error('--table is required for convert/load')
        chunks = converted_chunks(Path('/data') / (args.table + '.dat'))
        if args.command == 'convert':
            for chunk in chunks:
                sys.stdout.buffer.write(chunk)
        else:
            # Share the ClickHouse container's isolated network namespace. Data
            # stays inside Docker; the TSV conversion is the original importer.
            connection = http.client.HTTPConnection('127.0.0.1', 8123, timeout=1800)
            try:
                sql = f'INSERT INTO tpcds_test.{args.table} FORMAT TabSeparated'
                connection.request('POST', '/?query=' + urllib.parse.quote(sql),
                                   body=chunks, encode_chunked=True,
                                   headers={'Content-Type': 'application/octet-stream'})
                response = connection.getresponse()
                body = response.read()
                if response.status != 200 or body.strip():
                    raise RuntimeError(f'HTTP insert failed ({response.status}): ' + body.decode(errors='replace'))
            finally:
                connection.close()
    else:
        reference(args.memory_limit_gb)


if __name__ == '__main__':
    main()
