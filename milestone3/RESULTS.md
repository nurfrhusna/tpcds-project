# Milestone 3 — paired SF1/SF10 results

Completed on 17 November 2026 (Korea time). These are measurements of six selected TPC-DS query instances on one ClickHouse node, not official TPC-DS benchmark scores.

## Completed work

- Loaded both scale factors into fresh containers using the same original TSV conversion and Docker-internal HTTP loading path.
- Checked all 24 imported table row counts against the raw files at both scales. SF1 raw hashes also matched the previously validated dataset.
- Independently loaded the same SF10 files into DuckDB 1.4.1 and compared the team SQL with canonical SQL and ClickHouse output.
- All six SF10 comparisons passed with zero missing and zero extra rows. Ordered outputs also matched for all six queries.
- Ran two warm-up rounds and seven measured rounds for each query at each scale. All 84 measured executions and all 24 warm-up executions succeeded.
- Kept data generation, loading, and reference validation out of the benchmark measurement periods. Only one experiment container ran during each measurement.

## Environment and method

- Host CPU: AMD Ryzen 9 6900HS with Radeon Graphics. Host RAM reported by Windows: 31.23 GiB.
- OS: Microsoft Windows 11 Home, build 26300.
- Docker Engine: 29.9.3, Linux engine, 15.24 GiB allocated RAM.
- ClickHouse 26.10.3.7; identical container image, schema, SQL hashes, benchmark runner, and protocol across both runs.
- Container limits: 4 CPUs, 8 GiB memory, 8 GiB memory plus swap. Query limits: 4 threads, 6 GiB memory, 300-second timeout, one query at a time.
- Query-result and query-condition caches disabled. Two warm-up rounds preceded seven measured rounds; measured query order used seed 20261117.
- Warm queries and filesystem caches; no OS cache eviction. Background merges and mutations settled before merges were paused for timing.
- Runtime is ClickHouse server query duration from system.query_log. The headline value is the median of seven successful measured executions.

## Dataset sizes

| Scale | Total rows in 24 tables | Active table storage before timing (bytes) |
|---|---:|---:|
| SF1 | 19,557,375 | 607,028,206 |
| SF10 | 191,496,658 | 4,185,506,039 |

The nominal scale changes by 10. Actual total row counts and the work performed by each query do not necessarily change by exactly 10. Storage includes active ClickHouse parts and differs from raw .dat file size.

## SF10 correctness

| Query | DuckDB rows | ClickHouse rows | Missing | Extra | Team SQL vs canonical |
|---|---:|---:|---:|---:|---|
| Q3 | 100 | 100 | 0 | 0 | PASS |
| Q7 | 100 | 100 | 0 | 0 | PASS |
| Q31 | 288 | 288 | 0 | 0 | PASS |
| Q47 | 100 | 100 | 0 | 0 | PASS |
| Q64 | 33 | 33 | 0 | 0 | PASS |
| Q82 | 6 | 6 | 0 | 0 | PASS |

All 24 SF10 row counts matched between raw files, ClickHouse, and DuckDB. Matching consumes one unused row at a time, preserving duplicate counts. Integers and decimals compare exactly; floating values use relative tolerance 1e-9 and absolute tolerance 1e-8. FixedString NUL padding is removed before comparison. See the complete evidence in results/sf10/validation/.

## Runtime and variation

| Query | SF1 median (ms) | SF10 median (ms) | SF10 / SF1 | SF1 min–max (ms) | SF10 min–max (ms) | SF1 CV | SF10 CV |
|---|---:|---:|---:|---|---|---:|---:|
| Q3 | 18 | 83 | 4.61x | 16–18 | 75–86 | 4.51% | 4.26% |
| Q7 | 95 | 931 | 9.80x | 90–124 | 921–991 | 11.55% | 2.65% |
| Q31 | 175 | 1371 | 7.83x | 162–185 | 1358–1405 | 4.21% | 1.36% |
| Q47 | 525 | 3751 | 7.14x | 502–592 | 3674–3825 | 5.60% | 1.52% |
| Q64 | 221 | 728 | 3.29x | 214–252 | 717–766 | 6.60% | 2.43% |
| Q82 | 22 | 46 | 2.09x | 20–26 | 43–48 | 10.08% | 3.84% |

Each cell is based on seven successful measured runs; each scale had 42 successes and zero measured failures. CV is the sample standard deviation divided by the mean. All raw attempts, including warm-ups, are retained.

## Resource metrics

| Query | SF1 query memory (MiB) | SF10 query memory (MiB) | SF1 CPU time (s) | SF10 CPU time (s) | SF1 logical reads (MiB) | SF10 logical reads (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| Q3 | 3.36 | 2.21 | 0.032196 | 0.275015 | 10.92 | 96.50 |
| Q7 | 22.02 | 30.57 | 0.302711 | 3.524016 | 212.59 | 1574.11 |
| Q31 | 21.94 | 123.53 | 0.375864 | 5.183683 | 208.49 | 2004.62 |
| Q47 | 147.07 | 320.76 | 1.817152 | 14.419730 | 231.98 | 2260.73 |
| Q64 | 42.84 | 148.77 | 0.345638 | 2.263172 | 65.88 | 546.78 |
| Q82 | 5.62 | 15.41 | 0.029307 | 0.107304 | 7.83 | 32.94 |

Values are medians of successful measured runs. Memory is the query-log memory metric, not total container or host RAM. CPU time is (UserTimeMicroseconds + SystemTimeMicroseconds) / 1,000,000 from query profile events. read_bytes is logical bytes read; it is not physical disk throughput.

## Observations

- Q47 had the longest median runtime at both scales: 525 ms at SF1 and 3,751 ms at SF10.
- Q7 had the largest runtime ratio, 9.80x. Q82 had the smallest ratio, 2.09x.
- Runtime ratios ranged from 2.09x to 9.80x for a nominal 10x scale-factor increase. This describes these selected query instances and this warm-cache setup; it does not establish general algorithmic complexity.
- The logical-read ratios varied across queries. Input scale alone is not an exact measure of the work done by each filtered query.
- The smaller query-memory value for SF10 Q3 is an observed query-log measurement. It is not evidence that larger datasets generally need less memory.

## Reproduce and inspect

- Follow README.md and validation/README.md for the complete workflow.
- results/scaling_summary.csv and scaling_summary.json contain the exact comparison values.
- results/sf1/ and results/sf10/ contain summaries, all 54 attempts per scale, schedules, table parts/sizes, container limits, and first warm-up outputs.
- results/sf10/validation/ contains input-file hashes, typed DuckDB reference results, ClickHouse outputs, canonical comparisons, and all 24 table counts.
- results/environment.json records the hardware context. results/evidence_sha256.json records shared result hashes.
- The original complete runs remain in ignored runs/ folders. Raw data, ClickHouse storage, and reference databases remain in Docker volumes.
- examples/sf1/ is an earlier pilot. Use the new paired results/ measurements for the Milestone 3 comparison.

## Scope

This work evaluates data-size scalability on one node at a fixed CPU and memory limit. It does not evaluate distributed-node scaling, cold caches, concurrent-client throughput, or host physical disk throughput. These results are ready for plotting and report/presentation analysis; a final Milestone 3 paper or slide deck has not been authored here.
