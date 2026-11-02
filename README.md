

\# TPC-DS Benchmarking with ClickHouse



\## 1. Project Overview



This project implements a TPC-DS-based analytical benchmarking

workload using ClickHouse.



The project uses a subset of six TPC-DS queries to examine

execution performance, logical data reads, and memory usage.



The system runs locally using Docker and ClickHouse.

Python scripts automate data loading, query execution,

and collection of performance statistics.




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




\## 3. Project Structure



```text

tpcds-project/
├── docker-compose.yml
├── README.md
├── .gitignore
├── schema/
│   └── create\_tables\_nullable.sql
├── scripts/
│   ├── init\_database.ps1
│   ├── bulk\_import.py
│   └── run\_benchmark.py
├── queries/
│   ├── query\_03.sql
│   ├── query\_07.sql
│   ├── query\_31.sql
│   ├── query\_47.sql
│   ├── query\_64.sql
│   └── query\_82.sql
├── data/
│   └── (generated TPC-DS .dat files)
└── results/
&#x20;   └── (generated benchmark CSV files)

```



The generated dataset and local benchmark CSV files

are excluded from Git.



\## 4. Prerequisites



\- Windows with PowerShell

\- Docker Desktop with Linux containers enabled

\- Python 3.12 or compatible Python 3 version

\- Git

\- TPC-DS 4.0.0 data-generation toolkit



\## 5. Start ClickHouse



From the project root, run:



```powershell

docker compose up -d

```



Verify the container:



```powershell

docker ps

```



The container is named `tpcds-clickhouse`.



Note: The Docker Compose setup is intended for a fresh

environment. Do not use it to replace an existing ClickHouse

container without checking the container and volume names.



\## 6. Initialize the Database



Run:



```powershell

.\\scripts\\init\_database.ps1

```



This script:



1\. Creates the `tpcds\_test` database if it does not exist.

2\. Executes the SQL schema.

3\. Creates the 24 TPC-DS tables.



The schema uses ClickHouse MergeTree tables.



The `date\_dim.d\_date` column uses Date32 to support

historical dates before 1970.



Important: The initialization script is intended for

a fresh database. It has not yet been independently

validated on a clean teammate installation.



\## 7. Generate the TPC-DS Dataset



The project uses TPC-DS version 4.0.0 with Scale Factor 1.



The generated dataset consists of 24 table data files.



Obtain the TPC-DS data-generation toolkit from an

authorized source and build its `dsdgen` utility.



Generate SF1 data using the toolkit's data generator

and place the resulting `.dat` files in:



```text

data/

```



The `dbgen\_version.dat` metadata file is not imported.



The toolkit and generated data files are not included

in this repository.



Note: Exact toolkit build and generation instructions

for a fresh machine are still being documented.



\## 8. Import Data into ClickHouse



After generating the dataset and initializing the

database, run:



```powershell

python .\\scripts\\bulk\_import.py

```



The importer:



\- Reads the 24 TPC-DS `.dat` files.

\- Converts pipe-separated data to tab-separated input.

\- Converts empty fields into ClickHouse NULL values.

\- Loads each table into `tpcds\_test`.

\- Refuses to import when target tables already contain

&#x20; data, unless replacement is explicitly requested.



WARNING: Do not use the `--replace` option unless you

intend to delete and reload the existing table contents.




## 9. Selected Benchmark Queries

| Query | Workload Focus |
|---|---|
| Q3 | Basic aggregation |
| Q7 | Star-schema analytics |
| Q31 | Cross-channel analysis |
| Q47 | Analytical/window operations |
| Q64 | Complex multi-stage analysis |
| Q82 | Data-access-intensive candidate |



The SQL queries are based on the ClickHouse TPC-DS

benchmark query collection.



The workload categories describe our intended analysis;

actual CPU-bound or I/O-bound behavior must be

established through measurements.



\## 10. Run the Automated Benchmark



To run each query once:



```powershell

python .\\scripts\\run\_benchmark.py --runs 1

```



To run each query three times:



```powershell

python .\\scripts\\run\_benchmark.py --runs 3

```



The benchmark runner:



1\. Loads all six SQL queries.

2\. Executes each query against ClickHouse.

3\. Assigns a unique query ID to each execution.

4\. Retrieves statistics from `system.query\_log`.

5\. Saves the measurements to CSV.



Results are stored in:



```text

results/benchmark\_YYYYMMDD\_HHMMSS.csv

```




## 11. Performance Metrics

| Metric | Description |
|---|---|
| `execution_ms` | Server-reported query duration in milliseconds |
| `read_rows` | Number of rows read by ClickHouse |
| `read_bytes` | Logical bytes read by ClickHouse |
| `result_rows` | Number of output rows |
| `memory_usage_bytes` | Reported peak query memory usage |




The benchmark also records the query name, run number,

and unique query ID.



`read\_bytes` does not directly measure physical disk I/O.



The current runner does not measure CPU utilization

or physical disk throughput.



\## 12. Current Project Status



Completed locally:



\- ClickHouse environment running in Docker

\- TPC-DS SF1 data generated and imported

\- 24 tables populated

\- Six selected SQL queries executed successfully

\- Automated benchmark runner implemented

\- Initial repeated benchmark measurements collected



Remaining work:



\- Validate clean-environment reproduction

\- Complete setup documentation

\- Perform controlled benchmark experiments

\- Analyze execution time, logical reads, and memory

\- Investigate CPU and physical I/O behavior

\- Prepare performance graphs and project report



\## 13. Benchmark Limitations



The current experiments use a local machine and SF1 data.



Performance can vary due to caching, CPU scheduling,

memory availability, and background activity.



Repeated executions may benefit from warmed caches.



The results should not be presented as official,

fully compliant TPC-DS benchmark scores.



\## 14. References



\- TPC-DS Benchmark Specification, Version 4.0.0

\- ClickHouse Documentation: https://clickhouse.com/docs

\- ClickHouse TPC-DS Query Collection:

&#x20; https://github.com/ClickHouse/ClickHouse/tree/master/tests/benchmarks/tpc-ds/queries

```



