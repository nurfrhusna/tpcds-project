"""Join dsdgen chunks of large tables into memfd files and symlink them as <table>.dat.

/dev/shm on the node is half of RAM, so raw SF100 data and the databases do not fit there together.
memfd files use the same RAM without counting against that mount. Arguments: OUTDIR PARTS JOBS TABLE...
Takes chunk i once OUTDIR/.done<i> exists, so it can run next to dsdgen. Runs until killed (the files live as long as this process); writes OUTDIR/.memfd-ready when done.
"""
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

out, parts, jobs, tables = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:]


def build(table):
    fd = os.memfd_create(table)
    for i in range(1, parts + 1):
        chunk = out / f"{table}_{i}_{parts}.dat"
        while not (out / f".done{i}").exists():
            time.sleep(1)
        if not chunk.exists():
            continue
        with chunk.open("rb") as source:
            size, done = os.fstat(source.fileno()).st_size, 0
            while done < size:
                done += os.sendfile(fd, source.fileno(), done, min(size - done, 1 << 30))
        chunk.unlink()
    (out / f"{table}.dat").symlink_to(f"/proc/{os.getpid()}/fd/{fd}")


with ThreadPoolExecutor(jobs) as pool:
    list(pool.map(build, tables))
(out / ".memfd-ready").write_text("")
signal.pause()
