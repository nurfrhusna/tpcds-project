# Running the Milestone 3 benchmark on the Colgate University Supercomputer

The cluster uses Slurm and has no Docker, so the scripts run through `hpc/docker`, a small adapter that
accepts the Docker commands used by this project and runs the same images with Singularity.

| File | Purpose |
|---|---|
| `docker` | Docker command adapter for Singularity. Put this folder first on `PATH`. |
| `generate.sh`, `memfd_tables.py` | Generate the raw tables with parallel dsdgen chunks. Large SF100 tables are kept in anonymous memory files. |
| `prepare_parallel.py` | Row count checks from `prepare_volume.py` (without its built-in SF1 hash check, which was done separately); large tables load in line-aligned 1 GiB ranges at the same time. |
| `protocol.json` | `protocol.json` without container CPU and memory limits. Query settings, rounds and seed are unchanged. |
| `run_controlled.py` | `run_controlled.py` with one changed line: the container limit check is skipped when the protocol sets no limit. |
| `protocol_nolimit.json` | `protocol.json` without the per-query limits (4 threads, 6 GiB, 300 s). Rounds, seed and the other query settings are unchanged. |
| `run_controlled_nolimit.py` | `run_controlled.py` with one more changed line: no client timeout when the protocol sets no time limit. |

`protocol.json` and `run_controlled.py` (or the `_nolimit` versions) were copied over the versions in the parent folder on the node before each run.

## Two result sets

| Folder | Container limits | Query limits | Charts |
|---|---|---|---|
| [`../results-hpc-nolimit`](../results-hpc-nolimit) | none | none | `tpc-ds/figures/hpc-nolimit` |
| [`../results-hpc`](../results-hpc) | none | 4 threads, 6 GiB, 300 s | `tpc-ds/figures/hpc` |

The Milestone 3 report uses `results-hpc-nolimit`. Both sets have 126 of 126 successful runs, and the query results are equal.
Without the thread setting, ClickHouse reported `max_threads` as `auto(40)`, which is the number of cores on the node. The job could use 32 of them.
The 4-thread set was measured first. For the no-limit set, SF1 and SF10 were loaded again with 8 loaders instead of 24, and SF100 used the same database in both sets.

## Differences from the laptop run

- ClickHouse ran in Singularity CE 4.5.0 from the same `clickhouse/clickhouse-server:26.10.3.7` image, without container limits.
  The Slurm job had 32 cores and 200 GiB of memory on node n16.
- Database files were in `/dev/shm` (RAM), so no query read from a disk.
- The DuckDB reference ran with 24 threads and a 24 GB memory limit, and hashed the input files in parallel.
- Merged source parts were removed quickly during loading to save RAM. Merges were settled and paused before timing, as in the protocol.
- The first SF100 load stopped when the job reached its memory limit. It was repeated from an empty database with 8 loaders
  instead of 24. The raw files were not changed, so the second load reused the saved input hashes, and validation hashed the files again.
- The TPC-DS 4.0.0 source came from the public mirror `stanislawbartkowski/DSGen-software-code-4.0.0` (commit `678efb2b`).
  The generated SF1 and SF10 files have the same SHA-256 hashes as the team's saved SF1 and SF10 files.

Do not mix these results with `../results`, which come from a different machine and setup.
