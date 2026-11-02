
import argparse
import csv
import json
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
QUERY_DIR = PROJECT_DIR / "queries"
RESULTS_DIR = PROJECT_DIR / "results"

QUERIES = [3, 7, 31, 47, 64, 82]


# --------------------------------------------------
# Execute ClickHouse commands
# --------------------------------------------------

def clickhouse(container, database, sql, query_id=None):
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "clickhouse-client",
        f"--database={database}",
    ]

    if query_id is not None:
        command.append(f"--query_id={query_id}")

    command.extend(["--query", sql])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip()


# --------------------------------------------------
# Retrieve performance statistics
# --------------------------------------------------

def get_statistics(container, database, query_id):
    sql = f"""
    SELECT
        query_duration_ms,
        read_rows,
        read_bytes,
        result_rows,
        memory_usage
    FROM system.query_log
    WHERE query_id = '{query_id}'
      AND type = 'QueryFinish'
    ORDER BY event_time_microseconds DESC
    LIMIT 1
    FORMAT JSONEachRow
    """

    for attempt in range(10):
        # Ensure completed queries are written to query_log.
        clickhouse(
            container,
            database,
            "SYSTEM FLUSH LOGS",
        )

        output = clickhouse(
            container,
            database,
            sql,
        )

        if output:
            return json.loads(output.splitlines()[0])

        time.sleep(0.5)

    raise RuntimeError(
        f"Query statistics not found: {query_id}"
    )


# --------------------------------------------------
# Load and validate SQL
# --------------------------------------------------

def load_query(query_number):
    query_name = f"query_{query_number:02d}"
    query_path = QUERY_DIR / f"{query_name}.sql"

    if not query_path.exists():
        raise FileNotFoundError(
            f"Missing query file: {query_path}"
        )

    sql = query_path.read_text(
        encoding="utf-8-sig"
    ).strip()

    # Ignore leading SQL comment lines for validation.
    lines = sql.splitlines()

    while lines and (
        not lines[0].strip()
        or lines[0].lstrip().startswith("--")
    ):
        lines.pop(0)

    sql_to_check = "\n".join(lines).lstrip().lower()

    if not sql_to_check.startswith(("select", "with")):
        raise RuntimeError(
            f"Unexpected SQL statement: {query_path}"
        )

    return query_name, sql


# --------------------------------------------------
# Main benchmark workflow
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TPC-DS ClickHouse benchmark runner"
    )

    parser.add_argument(
        "--container",
        default="tpcds-clickhouse",
    )

    parser.add_argument(
        "--database",
        default="tpcds_test",
    )

    parser.add_argument(
        "--runs",
        type=int,
        default=3,
    )

    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    # Load all queries before starting.
    query_files = [
        load_query(number)
        for number in QUERIES
    ]

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    output_path = (
        RESULTS_DIR / f"benchmark_{timestamp}.csv"
    )

    fieldnames = [
        "query",
        "run",
        "query_id",
        "execution_ms",
        "read_rows",
        "read_bytes",
        "result_rows",
        "memory_usage_bytes",
    ]

    total = len(query_files) * args.runs

    print(
        f"Starting benchmark: {total} executions",
        flush=True,
    )

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        completed = 0

        for query_name, sql in query_files:

            for run_number in range(
                1,
                args.runs + 1,
            ):

                query_id = str(uuid.uuid4())

                print(
                    f"Running {query_name}, "
                    f"run {run_number}/{args.runs}...",
                    flush=True,
                )

                # Execute the analytical SQL query.
                clickhouse(
                    args.container,
                    args.database,
                    sql,
                    query_id=query_id,
                )

                # Retrieve server-side measurements.
                stats = get_statistics(
                    args.container,
                    args.database,
                    query_id,
                )

                writer.writerow({
                    "query": query_name,
                    "run": run_number,
                    "query_id": query_id,
                    "execution_ms": stats["query_duration_ms"],
                    "read_rows": stats["read_rows"],
                    "read_bytes": stats["read_bytes"],
                    "result_rows": stats["result_rows"],
                    "memory_usage_bytes": stats["memory_usage"],
                })

                file.flush()
                completed += 1

                print(
                    f"  Completed: "
                    f"{stats['query_duration_ms']} ms "
                    f"({completed}/{total})",
                    flush=True,
                )

    print()
    print("Benchmark completed successfully!")
    print(f"Total executions: {completed}")
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
