"""Run the recorded warm-cache protocol against an isolated ClickHouse node."""
import argparse
import csv
import datetime
import decimal
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
DOCKER = shutil.which("docker")
if not DOCKER:
    raise SystemExit("Docker was not found. Install Docker Desktop and add docker to PATH.")
sys.dont_write_bytecode = True
from validation_helpers import compare_bags, decode_value
from manage import PROTOCOL


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def docker(arguments, **kwargs):
    return subprocess.run([DOCKER] + arguments, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kwargs)


def checked_docker(arguments, **kwargs):
    result = docker(arguments, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def client(container, sql, settings=None, query_id=None, timeout=30):
    arguments = ["exec", "-i", container, "clickhouse-client", "--database=tpcds_test"]
    for key, value in (settings or {}).items():
        arguments.append(f"--{key}={value}")
    if query_id:
        arguments.append(f"--query_id={query_id}")
    return docker(arguments, input=sql, timeout=timeout)


def query(container, sql):
    result = client(container, sql)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def json_rows(container, sql):
    output = query(container, sql.rstrip("; ") + " FORMAT JSONEachRow")
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def query_statistics(container, query_id):
    sql = f"""SELECT query_id, toString(type) AS event_type,
        event_time_microseconds, query_duration_ms, read_rows, read_bytes,
        result_rows, memory_usage, exception_code, exception,
        ProfileEvents, Settings, toString(query_cache_usage) AS query_cache_usage
        FROM system.query_log
        WHERE query_id = '{query_id}' AND type != 'QueryStart'
        ORDER BY event_time_microseconds DESC LIMIT 1"""
    for attempt in range(10):
        query(container, "SYSTEM FLUSH LOGS")
        rows = json_rows(container, sql)
        if rows:
            return rows[0]
        time.sleep(0.5)
    return None


def settle_tables(container, timeout_seconds):
    stable = 0
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        merges = int(query(container, "SELECT count() FROM system.merges WHERE database='tpcds_test'"))
        mutations = int(query(container, "SELECT count() FROM system.mutations WHERE database='tpcds_test' AND NOT is_done"))
        stable = stable + 1 if merges == 0 and mutations == 0 else 0
        if stable >= 5:
            query(container, "SYSTEM STOP MERGES")
            if int(query(container, "SELECT count() FROM system.merges WHERE database='tpcds_test'")) == 0:
                return
            query(container, "SYSTEM START MERGES")
            stable = 0
        time.sleep(1)
    raise RuntimeError(f"Tables did not settle within {timeout_seconds} seconds")


def summarize(records, queries):
    summaries = []
    for number in queries:
        attempts = [r for r in records if r["phase"] == "measured" and r["query"] == number]
        good = [r for r in attempts if r["status"] == "ok"]
        summary = {"query": number, "successful_runs": len(good), "failed_runs": len(attempts) - len(good)}
        for metric in ["server_duration_ms", "read_rows", "read_bytes", "result_rows", "query_memory_bytes", "query_cpu_seconds", "linux_os_read_bytes"]:
            values = [r[metric] for r in good if r.get(metric) is not None]
            if values:
                summary[metric + "_median"] = statistics.median(values)
        times = [r["server_duration_ms"] for r in good]
        if times:
            deviation = statistics.stdev(times) if len(times) > 1 else 0
            summary.update({"duration_min_ms": min(times), "duration_max_ms": max(times),
                            "duration_stdev_ms": deviation,
                            "duration_cv": deviation / statistics.mean(times) if statistics.mean(times) else None})
        summaries.append(summary)
    return summaries


def decode_rows(rows, columns):
    decoded = []
    for row in rows:
        if len(row) != len(columns):
            raise ValueError("Unexpected number of output columns")
        decoded.append(tuple(decode_value(value, column["type"]) for value, column in zip(row, columns)))
    return decoded


def export_csv(path, records):
    fields = ["scale_factor", "phase", "round", "query", "query_id", "status", "started_utc",
              "server_duration_ms", "client_elapsed_ms", "read_rows", "read_bytes", "result_rows",
              "query_memory_bytes", "query_cpu_seconds", "linux_os_read_bytes", "stderr"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True)
    parser.add_argument("--sf", type=int, required=True, choices=PROTOCOL["scales"])
    parser.add_argument("--validation-dir", type=Path,
                        help="Directory containing a successful same-input validation for SF10 or SF100")
    parser.add_argument("--output", type=Path, help="New run directory, otherwise use a timestamped folder under runs/")
    args = parser.parse_args()
    protocol = PROTOCOL
    validation = None
    if args.sf > 1:
        if not args.validation_dir:
            parser.error(f"SF{args.sf} requires --validation-dir from validate_results.py")
        validation = json.loads((args.validation_dir / "validation.json").read_text(encoding="utf-8"))
        if (validation.get("status") != "PASS" or validation.get("scale_factor") != args.sf or
                not validation.get("all_24_table_counts_match") or
                sorted(q["query"] for q in validation.get("queries", [])) != sorted(protocol["queries"]) or
                not all(q["comparison"]["equal"] and q["project_vs_canonical"]["equal"] for q in validation["queries"])):
            raise RuntimeError(f"A successful complete SF{args.sf} validation is required")
    reference_dir = args.validation_dir if validation else ROOT / "references/sf1"
    tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    output = args.output.resolve() if args.output else ROOT / "runs" / f"sf{args.sf}_{tag}"
    output.mkdir(parents=True)
    manifest = {"status": "preparing", "scale_factor": args.sf, "container": args.container,
                "protocol": protocol, "query_hashes": {}, "sf1_regression": {}, "output": str(output),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "protocol_sha256": hashlib.sha256((ROOT / "protocol.json").read_bytes()).hexdigest(),
                "schema_sha256": hashlib.sha256((ROOT / "project-snapshot/schema/create_tables_nullable.sql").read_bytes()).hexdigest(),
                "result_regression": {}}
    if validation:
        manifest["validation_sha256"] = hashlib.sha256((args.validation_dir / "validation.json").read_bytes()).hexdigest()
        manifest["dataset_sha256"] = validation["dataset_sha256"]
    save_json(output / "manifest.json", manifest)
    records = []
    paused_merges = False
    try:
        engine = json.loads(checked_docker(["info", "--format", "{{json .}}"], timeout=30))
        manifest["environment"] = {
            "docker_engine_sha256": hashlib.sha256(engine["ID"].encode()).hexdigest(),
            "docker": {key: engine[key] for key in ["ServerVersion", "OSType", "Architecture", "NCPU", "MemTotal", "KernelVersion"]},
        }
        inspection = json.loads(checked_docker(["inspect", args.container], timeout=30))[0]
        save_json(output / "container.json", inspection)
        if not inspection["State"]["Running"]:
            raise RuntimeError("Start the experiment container before benchmarking")
        host = inspection["HostConfig"]
        if validation and (inspection["Config"].get("Labels") or {}).get("tpcds.dataset_sha256") != validation["dataset_sha256"]:
            raise RuntimeError(f"SF{args.sf} validation does not match this container's input fingerprint")
        if protocol["container_cpus"] is not None and (host["NanoCpus"] != protocol["container_cpus"] * 1000000000 or
                host["Memory"] != protocol["container_memory_bytes"] or
                host["MemorySwap"] != protocol["container_memory_swap_bytes"]):
            raise RuntimeError("Container resource limits differ from the protocol")
        active = checked_docker(["ps", "--format", "{{json .}}"], timeout=30)
        (output / "running_containers.jsonl").write_text(active, encoding="utf-8")
        helper_ids = checked_docker(["ps", "-q", "--filter", "label=tpcds.role"], timeout=30).split()
        for helper in helper_ids:
            helper_info = json.loads(checked_docker(["inspect", helper], timeout=30))[0]
            role = (helper_info["Config"].get("Labels") or {}).get("tpcds.role")
            state = helper_info["State"]
            if role in ("generator", "loader", "reference") and state["Running"] and not state["Paused"]:
                raise RuntimeError("A data generator, loader, or reference engine is running; stop it before measurement")
        ready_deadline = time.monotonic() + 60
        while True:
            try:
                ready = client(args.container, "SELECT 1", timeout=5)
                if ready.returncode == 0:
                    break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() >= ready_deadline:
                raise RuntimeError("ClickHouse did not become ready within 60 seconds")
            time.sleep(1)
        manifest["server_version"] = query(args.container, "SELECT version()")
        smoke = client(args.container, "SELECT 1", settings=protocol["query_settings"])
        if smoke.returncode:
            raise RuntimeError(smoke.stderr)
        settings = json_rows(args.container, "SELECT name,value,changed FROM system.settings ORDER BY name")
        save_json(output / "server_defaults.json", settings)
        paused_merges = True
        settle_tables(args.container, protocol["merge_settle_timeout_seconds"])
        parts = json_rows(args.container, "SELECT table, count() AS active_parts, sum(rows) AS rows, sum(bytes_on_disk) AS bytes_on_disk, sum(data_compressed_bytes) AS compressed_bytes, sum(data_uncompressed_bytes) AS uncompressed_bytes FROM system.parts WHERE database='tpcds_test' AND active GROUP BY table ORDER BY table")
        save_json(output / "tables_before.json", parts)
        if len(parts) != 24:
            raise RuntimeError("Expected 24 populated tables")
        if validation:
            validated_counts = {r["table"]: r["reference_rows"] for r in json.loads((args.validation_dir / "table_counts.json").read_text())}
            if any(int(t["rows"]) != validated_counts[t["table"]] for t in parts):
                raise RuntimeError(f"Current SF{args.sf} row counts differ from the validated dataset")
        if args.sf == 1:
            with (ROOT / "project-snapshot/results/sf1_table_counts.csv").open(encoding="utf-8-sig") as handle:
                expected_counts = {r["table"]: int(r["row_count"]) for r in csv.DictReader(handle)}
            if any(int(t["rows"]) != expected_counts[t["table"]] for t in parts):
                raise RuntimeError("SF1 table counts differ from the validated dataset")
        sql_files = {}
        for number in protocol["queries"]:
            path = ROOT / f"project-snapshot/queries/query_{number:02}.sql"
            manifest["query_hashes"][str(number)] = hashlib.sha256(path.read_bytes()).hexdigest()
            if validation and manifest["query_hashes"][str(number)] != validation["query_hashes"][str(number)]:
                raise RuntimeError(f"SQL changed after SF{args.sf} correctness validation")
            sql_files[number] = path.read_text(encoding="utf-8-sig").strip().rstrip(";")
        schedule = []
        rng = random.Random(protocol["random_seed"])
        for phase, rounds in [("warmup", protocol["warmup_rounds"]), ("measured", protocol["measured_rounds"])]:
            for round_number in range(1, rounds + 1):
                order = list(protocol["queries"])
                if phase == "measured":
                    rng.shuffle(order)
                for number in order:
                    schedule.append({"phase": phase, "round": round_number, "query": number})
        save_json(output / "schedule.json", schedule)
        manifest["status"] = "running"
        save_json(output / "manifest.json", manifest)
        with (output / "attempts.jsonl").open("w", encoding="utf-8") as journal:
            for step in schedule:
                record = dict(step, scale_factor=args.sf, query_id="m3_" + uuid.uuid4().hex,
                              started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                print(f"SF{args.sf} {step['phase']} {step['round']} Q{step['query']}", flush=True)
                start = time.perf_counter()
                stdout = ""
                try:
                    result = client(args.container, sql_files[step["query"]] + " FORMAT JSONCompactEachRow",
                                    settings=protocol["query_settings"], query_id=record["query_id"],
                                    timeout=protocol["query_settings"]["max_execution_time"] + 30)
                    stdout = result.stdout
                    record.update(status="ok" if result.returncode == 0 else "query_error",
                                  return_code=result.returncode, stderr=result.stderr)
                except subprocess.TimeoutExpired:
                    record.update(status="client_timeout", return_code=None, stderr="Client timeout after server timeout allowance")
                    try:
                        query(args.container, f"KILL QUERY WHERE query_id='{record['query_id']}' SYNC")
                    except Exception as exc:
                        record["cancellation_error"] = str(exc)
                except Exception as exc:
                    record.update(status="client_error", return_code=None, stderr=str(exc))
                record["client_elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
                try:
                    stats = query_statistics(args.container, record["query_id"])
                except Exception as exc:
                    stats = None
                    record["log_collection_error"] = str(exc)
                record["query_log"] = stats
                if stats:
                    events = stats["ProfileEvents"]
                    cpu_seconds = None
                    if "UserTimeMicroseconds" in events or "SystemTimeMicroseconds" in events:
                        cpu_seconds = (events.get("UserTimeMicroseconds", 0) + events.get("SystemTimeMicroseconds", 0)) / 1000000
                    record.update(server_duration_ms=stats["query_duration_ms"], read_rows=stats["read_rows"],
                                  read_bytes=stats["read_bytes"], result_rows=stats["result_rows"],
                                  query_memory_bytes=stats["memory_usage"],
                                  query_cpu_seconds=cpu_seconds,
                                  linux_os_read_bytes=events.get("OSReadBytes"))
                    if record["status"] == "ok" and stats["event_type"] != "QueryFinish":
                        record["status"] = "query_log_error"
                    if record["status"] == "ok" and stats["query_cache_usage"] not in ("None", "Unknown"):
                        record["status"] = "unexpected_query_cache"
                elif record["status"] == "ok":
                    record["status"] = "missing_query_log"
                if step["phase"] == "warmup" and step["round"] == 1 and record["status"] == "ok":
                    (output / f"query_{step['query']:02}_output.jsonl").write_text(stdout, encoding="utf-8")
                    reference = json.loads((reference_dir / f"query_{step['query']:02}_reference.json").read_text())
                    observed = [json.loads(line, parse_float=decimal.Decimal) for line in stdout.splitlines() if line.strip()]
                    expected_rows = decode_rows(reference["rows"], reference["columns"])
                    observed_rows = decode_rows(observed, reference["columns"])
                    comparison = compare_bags(expected_rows, observed_rows)
                    manifest["result_regression"][str(step["query"])] = comparison
                    if args.sf == 1:
                        manifest["sf1_regression"][str(step["query"])] = comparison
                    if not comparison["equal"]:
                        record["status"] = "regression_mismatch"
                records.append(record)
                journal.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                journal.flush()
                save_json(output / "summary.json", summarize(records, protocol["queries"]))
                save_json(output / "manifest.json", manifest)
                print("  " + record["status"] + " " + str(record.get("server_duration_ms")) + " ms", flush=True)
                if step["phase"] == "warmup" and record["status"] != "ok":
                    raise RuntimeError("Warm-up or regression failed; measurement stopped")
        manifest["status"] = "complete" if all(r["status"] == "ok" for r in records) else "complete_with_failures"
        save_json(output / "tables_after.json", json_rows(args.container, "SELECT table,count() AS active_parts,sum(rows) AS rows,sum(bytes_on_disk) AS bytes_on_disk FROM system.parts WHERE database='tpcds_test' AND active GROUP BY table ORDER BY table"))
    except Exception as exc:
        manifest.update(status="error", error=str(exc))
        raise
    finally:
        if paused_merges:
            client(args.container, "SYSTEM START MERGES")
        export_csv(output / "attempts.csv", records)
        save_json(output / "manifest.json", manifest)
        print("EVIDENCE", output, flush=True)


if __name__ == "__main__":
    main()
