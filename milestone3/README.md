# Team 12 — TPC-DS Milestone 3

Run the same six-query ClickHouse experiment on another teammate's computer.
This repository contains the SQL, schema, loading script, controlled measurement
script, protocol, SF1 reference results, and a saved SF1 example summary.
The original team project is kept unchanged; this is a separate experiment copy.

## What has actually been completed

- SF1 was loaded from TPC-DS 4.0.0 data. All 24 table counts matched the saved counts.
- All six SF1 outputs matched the saved Milestone 2 reference results, preserving duplicate counts.
- Two warm-up rounds and seven measured rounds were completed: all 42 measured executions succeeded.
- SF10 raw data has been generated on the original experiment PC, but SF10 loading, query validation, and timing are still pending.
- This is a selected TPC-DS workload study on one ClickHouse node, not an official TPC-DS benchmark score or a distributed-system test.

## Requirements

- Python 3.11 or newer; Python 3.12 was used for the recorded experiment. No pip packages are needed.
- Docker Desktop running Linux containers, with `docker` available in your terminal.
- Docker must have more than 8 GiB of memory available, because the ClickHouse container has an 8 GiB limit and Docker itself also needs memory.
- Enough free disk space for raw data, imported data, and Docker images. The recorded raw files are about 1.17 GiB for SF1 and 11.36 GiB for SF10; imported data and temporary files require additional space.
- The official TPC-DS 4.0.0 source ZIP, downloaded separately from TPC. Follow its download/license terms. Source code and generated datasets are not included here.

The commands below work from the repository folder. The workflow has been tested
on Windows with Docker Desktop's Linux engine and an x86-64 CPU. Other operating
systems and processor architectures have not been tested by this team.

## 1. Get the experiment files

Clone the team repository and open a terminal in its `milestone3/` folder. If you received this package as a standalone ZIP, open the folder containing `manage.py` instead.

```text
python --version
docker info
```

If this is a private repository, the owner must give each teammate access.

## 2. Build the data generator

Download **TPC-DS 4.0.0** from [TPC's tools page](https://www.tpc.org/tpc_documents_current_versions/current_specifications5.asp).
Extract the ZIP. Find the source folder that contains `tools/driver.c`.
Replace the sample path below with that folder's actual path.

```text
python manage.py build-toolkit --source-dir "C:/path/to/DSGen-software-code-4.0.0"
```

This builds `team12-tpcds-toolkit:4.0.0`. The local build copy is ignored by Git.
The Dockerfile uses the same build recipe as the original experiment, including
the `-fcommon` compiler option needed by this toolkit source.

## 3. Generate SF1

```text
python manage.py generate --sf 1 --output data/sf1
```

The generator writes to a fresh Docker volume first, then exports the completed files into the output folder. This avoids slow per-record writes through Windows shared folders. The raw Docker volume is retained, and its name is printed. During export, both the Docker copy and the host copy use disk space.

The output directory must be empty. If a teammate already has the same official
SF1 files, they can skip generation and use that folder in the next step.
The loader checks all 24 SF1 file hashes against our validated dataset before loading.
It stops if the files differ; it does not silently accept a different dataset.

## 4. Create a fresh ClickHouse container and load SF1

```text
python manage.py prepare --sf 1 --data-dir data/sf1 --name team12-m3-sf1
```

This creates a new container named `team12-m3-sf1` and a new volume named
`team12-m3-sf1-data`. It refuses to reuse either name if it already exists.
It loads the 24 tables with the original team's importer, then checks the SF1 row counts.
No host ports are published; the scripts use `docker exec` to access ClickHouse.
Input hashes, table counts, and local environment information are saved under `local/`.

If preparation fails, keep the evidence and choose a fresh `--name` after resolving
the problem. Do not run the importer repeatedly on a partly loaded database.

## 5. Run the same test

Close other heavy applications and stop or pause data generation before timing.
Do not run another benchmark at the same time.

```text
python run_controlled.py --container team12-m3-sf1 --sf 1
```

The script checks container limits, waits for merges and mutations to settle,
pauses merges during the run, and restores them afterward. It checks the first
warm-up output of each query against the saved SF1 reference results. A failed
warm-up or result check stops the measurement.

| Setting | Value |
|---|---|
| ClickHouse image | `clickhouse/clickhouse-server:26.10.3.7` |
| Container CPU limit | 4 CPUs |
| Container memory limit | 8 GiB |
| Container memory plus swap limit | 8 GiB |
| Query threads | 4 |
| Query memory limit | 6 GiB |
| Query timeout | 300 seconds |
| Concurrent queries | 1 |
| Queries | Q3, Q7, Q31, Q47, Q64, Q82 |
| Warm-up rounds | 2 |
| Measured rounds | 7 |
| Measured query order | Seeded shuffle, seed 20261117 |
| Query-result and query-condition caches | Disabled |
| Cache regime | Warm queries and filesystem caches; no OS cache eviction |

`protocol.json` contains the exact settings. Do not change settings or SQL during
an SF1/SF10 comparison. If a change is necessary, record it and rerun the baseline.

## 6. Find and share your results

Each run creates a new folder under `runs/`. It contains:

- `manifest.json`: protocol, SQL hashes, runner hash, SF1 result comparisons, and run status.
- `attempts.jsonl`: all warm-up and measured attempts, with raw query-log records.
- `attempts.csv`: the measurements in a flat table.
- `summary.json`: medians, ranges, sample standard deviations, and variation for successful measured runs, with failure counts.
- `container.json`, `server_defaults.json`, and `tables_before.json`: configuration and table evidence.
- `query_XX_output.jsonl`: the first warm-up result of each query.

`runs/` and `local/` are ignored by Git. To share results, send the run folder and
its matching preparation evidence to the team through your shared drive. These
files can include local computer information and folder paths, so review them
before publishing them outside the team.

After finishing:

```text
docker stop team12-m3-sf1
```

The data volume is retained. Start the same container with `docker start team12-m3-sf1`
if you need to run it again. Do not remove the data volume until its results are saved.

## SF10: the next experiment

```text
python manage.py generate --sf 10 --output data/sf10
python manage.py prepare --sf 10 --data-dir data/sf10 --name team12-m3-sf10
python run_controlled.py --container team12-m3-sf10 --sf 10
docker stop team12-m3-sf10
```

The runner supports SF10 timing but currently has saved reference outputs only
for SF1. An SF10 run does not establish SF10 query correctness; that requires a
separate reference comparison using the same SF10 input files. Do not describe
SF10 results as correctness-validated until that comparison is completed.

Compare SF1 and SF10 on the **same computer**, with the same resource limits,
using the median runtime, variation, query memory, CPU time, and logical reads.
Calculate the runtime ratio as `SF10 median / SF1 median` for each query.
Keep each computer's results separate: identical CPU and memory limits do not
make different CPU models, disks, Docker allocations, or host workloads equivalent.
This measures data-size scalability on one node; it does not measure distributed scalability.

## Saved example: first SF1 baseline

The example was measured on 17 November 2026 with an AMD Ryzen 9 6900HS,
Windows 11, Docker Desktop's Linux engine, and Docker Engine 29.9.3, using the
limits above. It is the original baseline, not a guarantee of another PC's timing.

| Query | Successful measured runs | Median server duration | Minimum | Maximum |
|---|---:|---:|---:|---:|
| Q3 | 7 | 16 ms | 15 ms | 24 ms |
| Q7 | 7 | 95 ms | 87 ms | 124 ms |
| Q31 | 7 | 164 ms | 159 ms | 188 ms |
| Q47 | 7 | 526 ms | 497 ms | 583 ms |
| Q64 | 7 | 222 ms | 204 ms | 246 ms |
| Q82 | 7 | 20 ms | 19 ms | 24 ms |

See `examples/sf1/summary.csv` and `summary.json` for the saved summary, `attempts.csv` for all 54 original attempts, and `validation.json` for the six SF1 result comparisons. The later package-verification run is separate from this saved baseline.
The benchmark records logical bytes read and available query profile events.
It has not measured host physical disk throughput. Missing I/O counters are not zero.

## Sources and provenance

- [TPC-DS specifications and tools](https://www.tpc.org/tpcds/).
- [ClickHouse TPC-DS query collection](https://github.com/ClickHouse/ClickHouse/tree/master/tests/benchmarks/tpc-ds/queries).
- The six SQL files, schema, importer, and SF1 table counts were copied unchanged
  from the team's original project. `source_sha256.json` records the original
  project snapshot hashes, including files not needed in this smaller package.
- `validation_helpers.py` preserves the typed comparison functions used in our
  Milestone 2 checks. Integers and decimals compare exactly; floating values use
  relative tolerance `1e-9` and absolute tolerance `1e-8`. Each matching row is
  consumed once, preserving duplicate counts.
- The shared runner changes local dependency paths and Docker discovery and
  adds runner/protocol hashes. The SQL and measurement protocol are unchanged.

No new license is granted for third-party material. Keep its original notices
and follow the TPC toolkit's terms when downloading or sharing it.

## Shared-package verification

On 17 November 2026, the standalone package successfully built the toolkit, generated and exported SF1, and reproduced all 24 saved input-file hashes. Its fresh ClickHouse import passed all 24 SF1 table-count checks. The shared runner completed 12 warm-up attempts and 42 measured attempts, and all six SF1 reference comparisons passed. See `PACKAGE_VERIFICATION.json`. This verifies the package on the original experiment PC; teammate machines and SF10 have not yet been tested.
