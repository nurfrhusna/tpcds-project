# Running the Milestone 3 benchmark on the Colgate University Supercomputer

The cluster uses Slurm and has no Docker, so the scripts run through `hpc/docker`, a small adapter that
accepts the Docker commands used by this project and runs the same images with Singularity.

| File | Purpose |
|---|---|
| `docker` | Docker command adapter for Singularity. Put this folder first on `PATH`. |
| `generate.sh`, `memfd_tables.py` | Generate the raw tables with parallel dsdgen chunks. Large SF100 tables are kept in anonymous memory files. |
| `prepare_parallel.py` | Same checks as `prepare_volume.py`; large tables load in line-aligned 1 GiB ranges at the same time. |
| `protocol.json` | `protocol.json` without container CPU and memory limits. Query settings, rounds and seed are unchanged. |
| `run_controlled.py` | `run_controlled.py` with one changed line: the container limit check is skipped when the protocol sets no limit. |

`protocol.json` and `run_controlled.py` were copied over the versions in the parent folder on the node before the run.

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

Results are in [`../results-hpc`](../results-hpc). Do not mix them with `../results`, which come from a different machine and setup.
