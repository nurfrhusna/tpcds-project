# Team 12 — Milestone 3: performance and data-size scalability

This folder contains the team's reproducible SF1/SF10 ClickHouse experiment.
Use [RESULTS.md](RESULTS.md) and `results/` for the paired measurements and
correctness evidence. `examples/sf1/` contains the earlier SF1 pilot, which is
kept for history and should not be mixed into the new paired comparison.

The workload consists of Q3, Q7, Q31, Q47, Q64, and Q82. It runs on one
ClickHouse node. These selected-query measurements are not official TPC-DS
scores and do not establish distributed-node scalability.

## Requirements

- Python 3.11 or newer. The recorded experiment used Python 3.12.
- Docker Desktop with Linux containers, with `docker` available in the terminal.
- Docker memory allocation above 8 GiB, plus enough host memory for Windows.
  The experiment container has an 8 GiB limit. Reference validation stops it
  temporarily so DuckDB can use a separate 6 GiB container.
- Free disk space for generated raw data, ClickHouse data, and a disk-backed
  DuckDB reference. SF10 raw files alone use about 11.36 GiB.
- The official TPC-DS **4.0.0** source download, obtained separately from
  [TPC](https://www.tpc.org/tpc_documents_current_versions/current_specifications5.asp).
  Follow its download terms. Source code and generated data are not in this repository.

No host pip installation is required. DuckDB 1.4.1 is installed inside the
validation image. This workflow has been tested on Windows and x86-64 Docker
Linux containers. Other operating systems and architectures have not been tested.

After cloning the team repository, open a terminal in `milestone3/`. All commands
below run from that folder. Start Docker Desktop first.

## 1. Build the two helper images

Extract the official source ZIP. Select the source folder containing
`tools/driver.c`; replace the example path with its actual location.

```text
python manage.py build-toolkit --source-dir "C:/path/to/DSGen-software-code-4.0.0"
docker build -t team12-tpcds-validation:1.4.1 -f validation/Dockerfile .
```

The first image is the official data generator. The second uses DuckDB for
independent reference checks and the team's original conversion function for
loading. Rebuild the validation image if its source files are changed.

## 2. Generate the raw datasets

Generate both scales before measuring anything:

```text
python manage.py generate --sf 1 --volume-only --volume-name team12-raw-sf1
python manage.py generate --sf 10 --volume-only --volume-name team12-raw-sf10
```

Each command requires a fresh volume name and refuses an existing one. If the
same raw datasets already exist, skip generation and use their actual volume
names below. To export new data to a host folder instead, the earlier
`python manage.py generate --sf 1 --output data/sf1` workflow is still supported.

## 3. Load and validate

```text
python prepare_volume.py --data-volume team12-raw-sf1 --sf 1 --name team12-m3-sf1
docker stop team12-m3-sf1
python prepare_volume.py --data-volume team12-raw-sf10 --sf 10 --name team12-m3-sf10
python validate_results.py --data-volume team12-raw-sf10 --container team12-m3-sf10 --sf 10 --output local/sf10-validation --stop-clickhouse-during-reference
```

The loaders create new containers and volumes and refuse to overwrite existing
ones. Raw data is mounted read-only. All 24 file hashes and row counts are
recorded. SF1 hashes must match the saved validated dataset. SF10 correctness
uses the exact same files in ClickHouse and DuckDB, with a second comparison
against saved canonical SQL. See [the validation method](validation/README.md).

The direct loader uses `converted_chunks` from the unchanged original importer.
It streams those TSV bytes to ClickHouse inside Docker, avoiding a large round
trip through Windows. Both scales must use the same loading method for the
paired comparison. The older host-folder loader remains available through
`manage.py prepare` for the original SF1 workflow.

If loading fails, keep its evidence and choose a fresh container name for a clean
retry. The validation output directory must also be new. Do not repeatedly
import into a partly loaded database.

## 4. Measure one container at a time

Wait for SF10 validation to report `PASS`. Then run:

```text
docker stop team12-m3-sf10
docker start team12-m3-sf1
python run_controlled.py --container team12-m3-sf1 --sf 1
docker stop team12-m3-sf1
docker start team12-m3-sf10
python run_controlled.py --container team12-m3-sf10 --sf 10 --validation-dir local/sf10-validation
docker stop team12-m3-sf10
```

Close heavy applications. Do not run generation, loading, reference validation,
or another benchmark during measurement. The runner checks for labeled helpers,
waits for the server to become ready, waits for merges and mutations to settle,
and pauses merges during timing. It restores merges afterward.

The first warm-up result of each query is checked against the saved independent
reference. For SF10 the runner also checks the successful validation report,
dataset fingerprint, SQL hashes, and all 24 table counts. A failed warm-up or
result check stops the measurement. Measured errors are saved and counted.

| Setting | Value |
|---|---|
| ClickHouse | `clickhouse/clickhouse-server:26.10.3.7` |
| Container CPU limit | 4 CPUs |
| Container memory / memory plus swap limit | 8 GiB / 8 GiB |
| Query threads / query memory limit | 4 / 6 GiB |
| Query timeout / concurrency | 300 seconds / 1 |
| Warm-up / measured rounds | 2 / 7 |
| Measured query order | Seeded shuffle, seed 20261117 |
| Query-result / query-condition caches | Disabled / disabled |
| Cache regime | Warm queries and filesystem caches; no OS cache eviction |

`protocol.json` is unchanged from the initial experiment. Use the same computer,
runner, schema, SQL, and settings for both scales. Different teammate PCs can
produce different runtimes even with the same container limits. Keep each PC's
paired results separate.

## 5. Collect and share the results

Each benchmark prints its new run folder under `runs/`. Replace the two run
folder placeholders below with the actual folders from your measurements:

```text
python collect_results.py --sf1-run runs/SF1_RUN_FOLDER --sf10-run runs/SF10_RUN_FOLDER --validation-dir local/sf10-validation --output results-new
```

The output folder must be new. The collector checks that the protocol, SQL,
schema, runner, and ClickHouse versions match across scales. It copies raw
attempt records, per-query summaries, table sizes, reviewed container limits,
SF10 correctness evidence, and a scaling comparison table. The optional
`--host-info` argument accepts a reviewed hardware JSON file without personal
identifiers. Docker and basic platform information are recorded automatically.

- `results/scaling_summary.csv`: runtimes, ratios, CPU time, query memory, and logical reads.
- `results/sf1/` and `results/sf10/`: paired run evidence, including all measured and warm-up attempts.
- `results/sf10/validation/`: input hashes, 24 table counts, six reference outputs, and comparisons.
- `results/environment.json`: hardware and Docker context.
- `results/evidence_sha256.json`: hashes of the shared result files.

Raw `.dat` files, reference databases, full local machine details, and unfinished
attempts remain in Docker volumes or ignored `data/`, `local/`, and `runs/`
folders. Share the small code and `results/` files through GitHub. Teammates can
read and analyze the recorded results without rerunning everything. Anyone who
repeats the experiment should retain their own full local evidence.

## Interpretation and limits

The runtime ratio is `SF10 median / SF1 median` for each query. Use all seven
measured repetitions and report variation and failures as well as the median.
The nominal scale factor changes by 10, but individual table sizes and the work
performed by each query do not necessarily grow by exactly 10.

`read_bytes` is a logical-read metric. Query memory is the recorded query-log
memory metric, not total host RAM. Query CPU time comes from available profile
events. This experiment does not measure host physical disk throughput, cold
cache behavior, concurrent-client throughput, or distributed-node scaling.

## Sources and provenance

- [TPC-DS specifications and tools](https://www.tpc.org/tpcds/).
- [ClickHouse TPC-DS query collection](https://github.com/ClickHouse/ClickHouse/tree/master/tests/benchmarks/tpc-ds/queries).
- `project-snapshot/` preserves the team's SQL, schema, original importer, and SF1 counts.
- `source_sha256.json` records the original project snapshot, including files not needed in this folder.
- `validation/` contains the schema, dialect adapter, and canonical SQL carried forward from the successful Milestone 2 reference check.
- `PACKAGE_VERIFICATION.json` records current verification. The earlier package verification is kept with the historical SF1 example.
- `package_sha256.json` records the current shared file hashes, excluding itself and ignored local data.

No new license is granted for third-party material. Keep its original notices
and follow the TPC toolkit's download terms.
