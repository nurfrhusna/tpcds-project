# Same-input correctness validation

The validator uses DuckDB **1.4.1** as an independent SQL engine. It loads the
same 24 TPC-DS `.dat` files used by ClickHouse, using explicit column types in
`schema.json`. It does not generate a second dataset with DuckDB's generator.

For each selected query it compares:

1. The team's SQL, with the minimum DuckDB dialect changes, against the saved
   canonical TPC-DS SQL extracted from DuckDB's TPC-DS extension during Milestone 2.
2. ClickHouse's output against the independent DuckDB output.

The comparator consumes each matching row once, so duplicates are preserved.
Integers and decimals compare exactly. Floating-point values use relative
tolerance `1e-9` and absolute tolerance `1e-8`. NULL matches only NULL.
The unordered comparison and ordered equality are recorded separately.
Every comparison must pass before the SF10 or SF100 benchmark starts.
For SF100, use the commands in [the desktop runbook](../DESKTOP_SF100.md).

The explicit reference schema and `sql_dialect.py` come from the successful
same-input Milestone 2 validation. The adapter changes `Float64` to `DOUBLE` in
Q31, fixes the outer CTE qualifier in Q47, and changes Q82's date-cast syntax.
Predicates and selected query instances are unchanged. Canonical Q47 includes
additional ORDER BY tie-breakers; any observed difference must be inspected,
not silently marked as a match.

## Run from the milestone3 folder

Build the helper image once:

```text
docker build -t team12-tpcds-validation:1.4.1 -f validation/Dockerfile .
```

If raw data already exists in a Docker volume, load it into a new experiment
container. Replace the example volume name with your raw-data volume:

```text
python prepare_volume.py --data-volume team12-raw-sf10 --sf 10 --name team12-m3-sf10
```

If you need to generate the raw data first, build the official toolkit as
described in the main README, then use:

```text
python manage.py generate --sf 10 --volume-only --volume-name team12-raw-sf10
```

`prepare_volume.py` mounts raw data read-only, records all 24 input hashes and
row counts, and refuses existing destination containers or data volumes.
It uses `converted_chunks` from the unchanged original importer. The converted
TSV bytes are sent over HTTP on Docker's internal loopback interface. The helper
shares the ClickHouse container's isolated network namespace; no host ports are
published. This avoids sending the large dataset through Windows twice.
The original host-folder loader remains available in `manage.py prepare`.

Validate the imported SF10 dataset:

```text
python validate_results.py --data-volume team12-raw-sf10 --container team12-m3-sf10 --sf 10 --output local/sf10-validation --stop-clickhouse-during-reference
```

The output directory must not already exist. The optional final flag stops the
experiment container after collecting its outputs and restarts it after the
reference work. This frees RAM for DuckDB. The reference container uses 4 CPUs
and a fresh disk-backed volume. SF1 and SF10 use a 6 GiB container limit and a
4 GB DuckDB limit. SF100 uses 10 GiB and 7 GB respectively. DuckDB can reorder
rows while loading large CSV files to reduce memory pressure. The validator
restores the default setting before running the six queries.
See [DuckDB workload tuning](https://duckdb.org/docs/1.4/guides/performance/how_to_tune_workloads).
These limits apply
to correctness validation. ClickHouse keeps the same resource limits at every
scale. Reference execution times are validation diagnostics.

After the report says `PASS`, run the benchmark:

```text
python run_controlled.py --container team12-m3-sf10 --sf 10 --validation-dir local/sf10-validation
```

The runner checks the validated dataset fingerprint, SQL hashes, table counts,
and the first warm-up output of all six queries. It then uses the unchanged
two-warm-up/seven-measured-round protocol. Do not run data generation, loading,
or reference validation concurrently with benchmark measurement.

If preparation fails, its partial destination volume is retained for inspection.
Use a fresh container name for a clean retry. Reference databases, raw datasets,
and full machine details remain in Docker volumes or ignored local folders.
Use `collect_results.py` to copy small, shareable evidence into `results/` after
both scale-factor runs finish.
