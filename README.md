
# TPC-DS Benchmarking with ClickHouse

## 1. Project Overview

This project implements a TPC-DS-based analytical benchmarking workload using ClickHouse.

The project uses a subset of six TPC-DS queries to examine execution performance, logical data reads, and memory usage.

The system runs locally using Docker and ClickHouse. Python scripts automate data loading, query execution, and collection of performance statistics.

The current implementation uses TPC-DS Scale Factor 1 (SF1). The results are preliminary measurements, not official TPC-DS benchmark scores.

## 2. Technology Stack

| Component | Technology |
|---|---|
| Database | ClickHouse 26.10.3.7 |
| Containerization | Docker Desktop / Docker Compose |
| Programming | Python 3.12 |
| Benchmark | TPC-DS 4.0.0 |
| Dataset | Scale Factor 1 (SF1) |
| Database name | `tpcds_test` |
| Storage engine | MergeTree |

## 3. Project Structure

```text
tpcds-project/
├── docker-compose.yml
├── README.md
├── .gitignore
├── convert_schema.py
├── schema/
│   └── create_tables_nullable.sql
├── scripts/
│   ├── init_database.ps1
│   ├── bulk_import.py
│   └── run_benchmark.py
├── queries/
│   ├── query_03.sql
│   ├── query_07.sql
│   ├── query_31.sql
│   ├── query_47.sql
│   ├── query_64.sql
│   └── query_82.sql
├── data/
│   └── (generated TPC-DS .dat files)
└── results/
    └── (generated benchmark CSV files)
```

The `data/` directory contains locally generated TPC-DS data files. The `results/` directory stores benchmark output files.

Generated datasets and benchmark CSV files are excluded from Git using `.gitignore`. These directories may not appear in a fresh clone until created locally.

## 4. Prerequisites

The following tools are required:

- Windows with PowerShell
- Docker Desktop with Linux containers enabled
- Python 3.12 or a compatible Python 3 version
- Git
- TPC-DS 4.0.0 data-generation toolkit

Docker Desktop must be running before starting ClickHouse.

## 5. Start ClickHouse

From the project root directory, run:

```powershell
docker compose up -d
```

Verify that the container is running:

```powershell
docker ps
```

The configured container name is:

```text
tpcds-clickhouse
```

The Docker Compose configuration uses the ClickHouse image version `26.10.3.7` and a persistent Docker volume.

**Important:** The Docker Compose setup is intended for a fresh environment. Do not run it to replace an existing ClickHouse container without checking the container and volume names.


## 6. Initialize the Database

After starting ClickHouse, initialize the database from the project root:

```powershell
.\scripts\init_database.ps1
```

The initialization script is intended to:

1. Create the `tpcds_test` database if it does not exist.
2. Execute the SQL schema.
3. Create the 24 TPC-DS tables.

The schema uses ClickHouse MergeTree tables.

The `date_dim.d_date` column uses `Date32` to support historical dates before 1970.

**Important:** The initialization script has passed a PowerShell syntax check, but its complete execution has not yet been independently validated on a clean installation.

The existing populated local database should not be deleted or replaced for setup testing.

## 7. Generate the TPC-DS Dataset

The project uses TPC-DS version 4.0.0 with Scale Factor 1 (SF1).

The generated dataset consists of data files for 24 TPC-DS tables.

To prepare the dataset:

1. Obtain the TPC-DS 4.0.0 data-generation toolkit from an authorized source.
2. Build the toolkit's `dsdgen` utility.
3. Generate TPC-DS SF1 data.
4. Place the generated `.dat` files inside the project's `data/` directory.

Expected location:

```text
data/
├── customer.dat
├── date_dim.dat
├── store_sales.dat
├── ...
└── (other generated TPC-DS table files)
```

The `dbgen_version.dat` metadata file is not imported as a database table.

The toolkit source code and generated data files are not included in this GitHub repository.

**Note:** Exact toolkit build commands and dataset-generation instructions for a fresh machine are still being documented.

## 8. Import Data into ClickHouse

After generating the dataset and initializing the database, run:

```powershell
python .\scripts\bulk_import.py
```

The importer:

1. Reads the generated TPC-DS `.dat` files.
2. Converts pipe-separated input into tab-separated input.
3. Handles empty fields for nullable ClickHouse columns.
4. Loads the data into the `tpcds_test` database.
5. Refuses to import if target tables already contain data, unless replacement is explicitly requested.

The default configuration uses:

| Setting | Default |
|---|---|
| Database | `tpcds_test` |
| Container | `tpcds-clickhouse` |
| Data directory | `data/` |

**Warning:** Do not use the `--replace` option unless you intentionally want to clear and reload the existing table contents.

The existing populated database should be preserved.

## 9. Selected Benchmark Queries

Six queries were selected to represent different analytical workload characteristics.

| Query | Workload Focus |
|---|---|
| Q3 | Basic aggregation |
| Q7 | Star-schema analytics |
| Q31 | Cross-channel analysis |
| Q47 | Analytical/window operations |
| Q64 | Complex multi-stage analysis |
| Q82 | Data-access-intensive candidate |

The SQL queries are based on the ClickHouse TPC-DS benchmark query collection.

Query files are stored in the `queries/` directory.

All six selected queries have been executed successfully against the local SF1 database.

The workload categories describe the intended analysis. Actual CPU-bound or I/O-bound behavior must be established through measurements rather than assumed from query structure alone.

## 10. Run the Automated Benchmark

The benchmark runner executes the selected SQL queries and collects performance statistics from ClickHouse.

To execute each query once:

```powershell
python .\scripts\run_benchmark.py --runs 1
```

To execute each query three times:

```powershell
python .\scripts\run_benchmark.py --runs 3
```

The benchmark runner:

1. Loads the six SQL query files.
2. Executes each query against ClickHouse.
3. Assigns a unique query ID to each execution.
4. Retrieves performance statistics from `system.query_log`.
5. Saves the measurements to a CSV file.

The generated results are stored in:

```text
results/benchmark_YYYYMMDD_HHMMSS.csv
```

The benchmark runner has been tested locally with:

- One execution per query (6 total executions)
- Three executions per query (18 total executions)

Both preliminary benchmark runs completed successfully.

Repeated executions may benefit from warmed caches. These measurements should not be interpreted as controlled cold-cache experiments.

## 11. Performance Metrics

The automated benchmark collects the following measurements:

| Metric | Description |
|---|---|
| `execution_ms` | Server-reported query duration in milliseconds |
| `read_rows` | Number of rows read by ClickHouse |
| `read_bytes` | Logical bytes read by ClickHouse |
| `result_rows` | Number of output rows |
| `memory_usage_bytes` | Reported peak query memory usage |

The benchmark also records the query name, run number, and unique query ID.

**Important measurement limitations:**

- `read_bytes` does not directly measure physical disk I/O.
- The current benchmark runner does not directly measure CPU utilization.
- Physical disk throughput is not currently collected.
- Query execution times may be affected by caching and background system activity.

Additional measurements are required to investigate CPU-intensive and I/O-intensive query behavior.

## 12. Current Project Status

### Completed Locally

- [x] Set up ClickHouse in Docker.
- [x] Generate TPC-DS SF1 data.
- [x] Create and populate 24 TPC-DS tables.
- [x] Execute six selected SQL queries successfully.
- [x] Implement an automated Python benchmark runner.
- [x] Collect initial repeated benchmark measurements.
- [x] Create a Git repository and upload project code to GitHub.

### Remaining Work

- [ ] Validate setup on a fresh machine.
- [ ] Complete reproducible toolkit build and dataset-generation instructions.
- [ ] Verify database initialization on a clean installation.
- [ ] Perform controlled benchmark experiments.
- [ ] Analyze query execution time, logical reads, and memory usage.
- [ ] Investigate CPU utilization and physical disk I/O behavior.
- [ ] Prepare performance graphs and comparative analysis.
- [ ] Complete the project report.

## 13. Benchmark Limitations

The current experiments use a local machine and TPC-DS Scale Factor 1 data.

Performance can vary due to:

- Operating system scheduling
- CPU availability
- Memory availability
- Query and filesystem caching
- Background processes
- Docker resource allocation
- ClickHouse configuration

Repeated executions may benefit from warmed caches.

The current benchmark implementation focuses on execution time, logical data reads, and reported memory usage.

It does not yet provide comprehensive CPU utilization or physical disk I/O measurements.

The results should not be presented as official, fully compliant TPC-DS benchmark scores.

## 14. References

- TPC-DS Benchmark Specification, Version 4.0.0
- [ClickHouse TPC-DS Benchmark Query Collection](https://github.com/ClickHouse/ClickHouse/tree/master/tests/benchmarks/tpc-ds/queries)
