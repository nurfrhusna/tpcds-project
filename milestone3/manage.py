"""Prepare an isolated copy of the team's experiment. Uses Python's standard library."""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT / "protocol.json").read_text(encoding="utf-8"))
TOOLKIT_IMAGE = "team12-tpcds-toolkit:4.0.0"


def docker(*args, input=None, capture=True):
    executable = shutil.which("docker")
    if not executable:
        raise RuntimeError("Docker was not found. Install Docker Desktop and add docker to PATH.")
    result = subprocess.run([executable, *map(str, args)], input=input,
                            text=True, encoding="utf-8", errors="replace",
                            capture_output=capture)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() if capture else "Docker command failed.")
    return result.stdout if capture else ""


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def build(args):
    source = args.source_dir.resolve(strict=True)
    if not (source / "tools" / "driver.c").is_file():
        raise RuntimeError("Select the extracted TPC-DS 4.0.0 source folder containing tools/driver.c.")
    context = ROOT / "local" / ("toolkit-build-" + uuid.uuid4().hex[:8])
    context.mkdir(parents=True)
    shutil.copytree(source, context / "DSGen-software-code-4.0.0")
    shutil.copyfile(ROOT / "toolkit/Dockerfile", context / "Dockerfile")
    shutil.copyfile(ROOT / "toolkit/.dockerignore", context / ".dockerignore")
    docker("build", "-t", TOOLKIT_IMAGE, context, capture=False)


def generate(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError("Choose an empty output folder; existing data will not be overwritten.")
    name = "team12-generator-" + uuid.uuid4().hex[:10]
    volume = name + "-data"
    print("Generating in Docker volume:", volume, flush=True)
    docker("run", "--rm", "--name", name, "--label", "tpcds.role=generator",
           "--network", "none", "--cpus", "4", "--memory", "2g",
           "--mount", f"type=volume,source={volume},target=/output",
           TOOLKIT_IMAGE, "-SCALE", args.sf, "-DIR", "/output", capture=False)
    print("Copying generated files to:", output, flush=True)
    command = [shutil.which("docker"), "run", "--rm", "--network", "none",
               "--mount", f"type=volume,source={volume},target=/data,readonly",
               "--entrypoint", "tar", TOOLKIT_IMAGE, "-C", "/data", "-cf", "-", "."]
    expected = set(json.loads((ROOT / "sf1_input_sha256.json").read_text(encoding="utf-8")))
    allowed = {table + ".dat" for table in expected} | {"dbgen_version.dat"}
    copied = set()
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    if member.isdir() and member.name in (".", "./"):
                        continue
                    filename = member.name.removeprefix("./")
                    if not member.isfile() or filename not in allowed or filename in copied:
                        raise RuntimeError("Unexpected file in generated data: " + member.name)
                    with (output / filename).open("xb") as target:
                        shutil.copyfileobj(archive.extractfile(member), target, length=4 * 1024 * 1024)
                    copied.add(filename)
            process.stdout.close()
            if process.wait():
                raise RuntimeError("Docker data export failed; generated volume is retained: " + volume)
        except Exception:
            process.kill()
            process.wait()
            raise
    if not {table + ".dat" for table in expected} <= copied:
        raise RuntimeError("Generated data is incomplete; volume is retained: " + volume)
    print("Generated volume retained:", volume)
    print("Generated data:", output)


def prepare(args):
    data = args.data_dir.resolve(strict=True)
    files = {p.stem: p for p in data.glob("*.dat") if p.stem != "dbgen_version"}
    expected = json.loads((ROOT / "sf1_input_sha256.json").read_text(encoding="utf-8"))
    if set(files) != set(expected):
        raise RuntimeError("Expected the 24 TPC-DS table files, plus optional dbgen_version.dat.")
    print("Hashing the 24 input files...", flush=True)
    hashes = {}
    for table, path in sorted(files.items()):
        with path.open("rb") as handle:
            hashes[table] = hashlib.file_digest(handle, "sha256").hexdigest()
    if args.sf == 1 and hashes != expected:
        raise RuntimeError("SF1 input hashes differ from the validated dataset. Use TPC-DS 4.0.0 default SF1 generation.")
    name = args.name or f"team12-m3-sf{args.sf}-{uuid.uuid4().hex[:8]}"
    volume = name + "-data"
    # Names are reserved for new resources. Refuse existing containers or volumes.
    existing_containers = docker("container", "ls", "-a", "--format", "{{.Names}}").splitlines()
    existing_volumes = docker("volume", "ls", "--format", "{{.Name}}").splitlines()
    if name in existing_containers or volume in existing_volumes:
        raise RuntimeError("Container or volume already exists. Choose a new --name.")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    evidence = ROOT / "local" / ("prepare-sf" + str(args.sf) + "-" + stamp)
    save(evidence / "input_sha256.json", hashes)
    save(evidence / "host.json", {"platform": platform.platform(), "machine": platform.machine(),
                                 "python": platform.python_version(),
                                 "docker_info": json.loads(docker("info", "--format", "{{json .}}"))})
    state = {"status": "preparing", "scale_factor": args.sf, "container": name,
             "volume": volume, "data_directory": str(data), "sf1_hashes_match": args.sf == 1}
    save(evidence / "state.json", state)
    try:
        docker("run", "-d", "--name", name, "--label", "tpcds.milestone=3",
               "--label", "tpcds.role=benchmark", "--network", "none",
               "--cpus", PROTOCOL["container_cpus"],
               "--memory", PROTOCOL["container_memory_bytes"],
               "--memory-swap", PROTOCOL["container_memory_swap_bytes"],
               "--mount", f"type=volume,source={volume},target=/var/lib/clickhouse",
               PROTOCOL["clickhouse_image"])
        deadline = time.monotonic() + 120
        while True:
            try:
                docker("exec", name, "clickhouse-client", "--query", "SELECT 1")
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("ClickHouse did not become ready in 120 seconds.")
                time.sleep(1)
        docker("exec", name, "clickhouse-client", "--query", "CREATE DATABASE tpcds_test")
        schema = (ROOT / "project-snapshot/schema/create_tables_nullable.sql").read_text(encoding="utf-8-sig")
        docker("exec", "-i", name, "clickhouse-client", "--database=tpcds_test", "--multiquery", input=schema)
        subprocess.run([sys.executable, str(ROOT / "project-snapshot/scripts/bulk_import.py"),
                        "--container", name, "--data-dir", str(data)], check=True)
        rows = []
        for table in sorted(files):
            count = int(docker("exec", name, "clickhouse-client", "--database=tpcds_test",
                               "--query", f"SELECT count() FROM {table}"))
            rows.append({"table": table, "row_count": count})
        save(evidence / "table_counts.json", rows)
        if args.sf == 1:
            with (ROOT / "project-snapshot/results/sf1_table_counts.csv").open(encoding="utf-8-sig") as handle:
                expected_rows = {r["table"]: int(r["row_count"]) for r in csv.DictReader(handle)}
            if any(r["row_count"] != expected_rows[r["table"]] for r in rows):
                raise RuntimeError("Loaded SF1 table row counts do not match the saved counts.")
        state["status"] = "ready"
    except Exception as exc:
        state.update(status="error", error=str(exc))
        raise
    finally:
        save(evidence / "state.json", state)
        print("Preparation evidence:", evidence)
    print("Container:", name)
    print(f"Run: python run_controlled.py --container {name} --sf {args.sf}")
    print(f"After timing: docker stop {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("build-toolkit", help="Build from an extracted official TPC-DS 4.0.0 source download")
    p.add_argument("--source-dir", type=Path, required=True)
    p.set_defaults(action=build)
    p = commands.add_parser("generate", help="Generate new SF1 or SF10 files into an empty folder")
    p.add_argument("--sf", type=int, choices=[1, 10], required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(action=generate)
    p = commands.add_parser("prepare", help="Load into a new isolated container and volume")
    p.add_argument("--sf", type=int, choices=[1, 10], required=True)
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--name", help="Optional new container name")
    p.set_defaults(action=prepare)
    args = parser.parse_args()
    args.action(args)


if __name__ == "__main__":
    main()
