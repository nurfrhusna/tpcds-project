
import argparse
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if PROJECT_DIR.name in ("scripts", "codes"):
    PROJECT_DIR = PROJECT_DIR.parent

BATCH_SIZE = 4 * 1024 * 1024


def run_clickhouse(container, database, query):
    command = [
        "docker", "exec", container,
        "clickhouse-client",
        "--database", database,
        "--query", query,
    ]
    return subprocess.check_output(command, text=True).strip()


def converted_chunks(path):
    with path.open("rb", buffering=BATCH_SIZE) as source:
        buffer = bytearray()

        for line in source:
            line = line.rstrip(b"\r\n")

            if not line.endswith(b"|"):
                raise ValueError(f"Missing trailing pipe in {path}")

            fields = line[:-1].split(b"|")

            converted = b"\t".join(
                b"\\N" if field == b"" else field
                for field in fields
            ) + b"\n"

            buffer.extend(converted)

            if len(buffer) >= BATCH_SIZE:
                yield bytes(buffer)
                buffer.clear()

        if buffer:
            yield bytes(buffer)


def import_table(path, container, database):
    table = path.stem
    print(f"Importing {table}...", flush=True)

    command = [
        "docker", "exec", "-i", container,
        "clickhouse-client",
        "--database", database,
        "--query", f"INSERT INTO {table} FORMAT TabSeparated",
    ]

    process = subprocess.Popen(command, stdin=subprocess.PIPE)

    try:
        for chunk in converted_chunks(path):
            process.stdin.write(chunk)

        process.stdin.close()
        result = process.wait()

        if result != 0:
            raise RuntimeError(f"Import failed: {table}")

    except Exception:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise

    print(f"Finished {table}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Import TPC-DS SF1 data into ClickHouse"
    )
    parser.add_argument("--database", default="tpcds_test")
    parser.add_argument("--container", default="tpcds-clickhouse")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_DIR / "data",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing table rows before reimporting",
    )
    args = parser.parse_args()

    files = sorted(
        p for p in args.data_dir.glob("*.dat")
        if p.name != "dbgen_version.dat"
    )

    if len(files) != 24:
        raise RuntimeError(
            f"Expected 24 data files, found {len(files)}"
        )

    existing = []
    for path in files:
        count = int(run_clickhouse(
            args.container,
            args.database,
            f"SELECT count() FROM {path.stem}",
        ))
        if count > 0:
            existing.append(path.stem)

    if existing and not args.replace:
        raise RuntimeError(
            "Import stopped: some tables already contain data: "
            + ", ".join(existing)
            + ". Use --replace only if you intend to reload all tables."
        )

    if args.replace:
        print("Replacing existing table data...", flush=True)
        for path in files:
            run_clickhouse(
                args.container,
                args.database,
                f"TRUNCATE TABLE {path.stem}",
            )

    for path in files:
        import_table(path, args.container, args.database)

    print("All 24 tables imported successfully!")


if __name__ == "__main__":
    main()
