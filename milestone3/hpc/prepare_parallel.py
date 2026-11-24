"""prepare_volume.py with large tables split into line-aligned ranges that load at the same time.

Every range goes through the same converted_chunks function as the serial loader. Row counts are
checked per table in the same way. Usage: prepare_parallel.py --data-volume V --sf N --name C [--jobs 24]
"""
import argparse
import datetime
import http.client
import io
import json
import os
import re
import sys
import time
import urllib.parse
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manage import ROOT, PROTOCOL, docker, save
from prepare_volume import raw_inventory

sys.path.insert(0, str(ROOT / "project-snapshot/scripts"))
from bulk_import import converted_chunks

STATE = Path(os.environ["TPCDS_STATE"])
RANGE_BYTES = 1 << 30


class RangeFile(io.RawIOBase):
    def __init__(self, path, start, end):
        self.f = open(path, "rb", buffering=0)
        self.f.seek(start)
        self.left = end - start

    def readable(self):
        return True

    def readinto(self, b):
        n = min(len(b), self.left)
        if n == 0:
            return 0
        got = self.f.readinto(memoryview(b)[:n])
        self.left -= got
        return got


class RangePath:
    def __init__(self, path, start, end):
        self.args = (path, start, end)

    def open(self, mode, buffering):
        return io.BufferedReader(RangeFile(*self.args), buffering)

    def __str__(self):
        return "%s[%d:%d]" % self.args


def ranges(path):
    size = os.path.getsize(path)
    cuts = [0]
    with open(path, "rb") as f:
        for target in range(RANGE_BYTES, size, RANGE_BYTES):
            f.seek(target)
            f.readline()
            if cuts[-1] < f.tell() < size:
                cuts.append(f.tell())
    return list(zip(cuts, cuts[1:] + [size]))


def load(job):
    container, table, path, start, end = job
    pw = (STATE / "containers" / container / "pw").read_text().strip()
    c = http.client.HTTPConnection("127.0.0.1", 8123, timeout=3600)
    sql = f"INSERT INTO tpcds_test.{table} FORMAT TabSeparated"
    c.request("POST", "/?query=" + urllib.parse.quote(sql), body=converted_chunks(RangePath(path, start, end)), encode_chunked=True,
              headers={"Content-Type": "application/octet-stream", "X-ClickHouse-User": "default", "X-ClickHouse-Key": pw})
    r = c.getresponse()
    body = r.read()
    if r.status != 200 or body.strip():
        raise RuntimeError(f"HTTP insert failed ({r.status}): " + body.decode(errors="replace"))
    return table


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-volume", required=True)
    p.add_argument("--sf", type=int, choices=PROTOCOL["scales"], required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--jobs", type=int, default=24)
    p.add_argument("--manifest", help="input_manifest.json saved by an earlier attempt on the same unchanged raw files")
    a = p.parse_args()
    name, vol = a.name, a.name + "-data"
    if name in docker("ps", "-a", "--format", "{{.Names}}").splitlines() or vol in docker("volume", "ls", "--format", "{{.Name}}").splitlines():
        raise RuntimeError("Container or volume exists; choose a new --name")
    evidence = ROOT / "local" / f"prepare-sf{a.sf}-{datetime.datetime.now():%Y%m%d_%H%M%S}-{uuid.uuid4().hex[:6]}"
    data = json.loads(Path(a.manifest).read_text()) if a.manifest else raw_inventory(a.data_volume)
    scale = re.search(r"-SCALE\s+(\d+)\b", data["metadata"])
    if not scale or int(scale[1]) != a.sf or not data["metadata"].startswith("4.0.0|"):
        raise RuntimeError("Generator metadata does not match TPC-DS 4.0.0 and the requested scale")
    save(evidence / "input_manifest.json", data)
    state = {"status": "preparing", "container": name, "volume": vol, "raw_volume": a.data_volume, "scale_factor": a.sf,
             "dataset_sha256": data["dataset_sha256"], "protocol": PROTOCOL, "loader": "parallel ranges", "jobs": a.jobs}
    save(evidence / "state.json", state)
    docker("run", "-d", "--name", name, "--label", "tpcds.milestone=3", "--label", "tpcds.role=benchmark",
           "--label", "tpcds.dataset_sha256=" + data["dataset_sha256"], "--mount", f"type=volume,source={vol},target=/var/lib/clickhouse",
           PROTOCOL["clickhouse_image"])
    deadline = time.monotonic() + 120
    while True:
        try:
            docker("exec", name, "clickhouse-client", "--query", "SELECT 1")
            break
        except RuntimeError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
    docker("exec", name, "clickhouse-client", "--query", "CREATE DATABASE tpcds_test")
    docker("exec", "-i", name, "clickhouse-client", "--database=tpcds_test", "--multiquery",
           input=(ROOT / "project-snapshot/schema/create_tables_nullable.sql").read_text(encoding="utf-8-sig"))
    raw = STATE / "volumes" / a.data_volume
    jobs = [(name, t, str(raw / f"{t}.dat"), s, e) for t in data["files"] for s, e in ranges(raw / f"{t}.dat")]
    print(len(jobs), "ranges", flush=True)
    with ProcessPoolExecutor(a.jobs) as pool:
        for i, _ in enumerate(pool.map(load, jobs), 1):
            if i % 10 == 0:
                print(f"{i}/{len(jobs)} ranges loaded", flush=True)
    counts = []
    for t, info in data["files"].items():
        n = int(docker("exec", name, "clickhouse-client", "--database=tpcds_test", "--query", f"SELECT count() FROM {t}"))
        counts.append({"table": t, "raw_rows": info["rows"], "clickhouse_rows": n, "match": n == info["rows"]})
    save(evidence / "table_counts.json", counts)
    if not all(c["match"] for c in counts):
        raise RuntimeError("Imported row count differs from raw data: " + ", ".join(c["table"] for c in counts if not c["match"]))
    state["status"] = "ready"
    save(evidence / "state.json", state)
    print("Ready:", name, flush=True)


if __name__ == "__main__":
    main()
