# Run SF1, SF10, and SF100 on the 9800X3D desktop

Run all three scales on the Ryzen 7 9800X3D desktop with its 32 GB RAM.
Use the three new runs for the desktop comparison. The completed laptop
experiment is documented in [RESULTS.md](RESULTS.md).

## 1. Prepare the desktop

- Open PowerShell in the latest checkout's `milestone3` folder. Start Docker
  Desktop in Linux-container mode and use Python 3.11 or newer.
- Check `docker info` for at least four visible CPUs and enough Docker VM memory
  for the 10 GiB validation container plus Docker itself. Around 15–16 GiB of VM
  memory is a reasonable starting point on this 32 GB PC. Keep the allocation
  fixed during the study. See [Docker Desktop settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/#vm-resources).
- Check free space on the drive that contains Docker's Linux disk image.
  Budget a few hundred GiB for SF100 raw files, ClickHouse storage, the DuckDB
  reference, and temporary files. This is a planning estimate. Keep raw data in
  Docker volumes to avoid an additional host copy.
- Use the official TPC-DS 4.0.0 source. Replace the sample path with the
  extracted folder that contains `tools/driver.c`. The current workflow runs on
  the CPU and requires no RTX 5090 setup.

```powershell
python --version
docker info
python manage.py build-toolkit --source-dir "C:/path/to/DSGen-software-code-4.0.0"
docker build -t team12-tpcds-validation:1.4.1 -f validation/Dockerfile .
```

## 2. Run one scale at a time

First set `$Sf = 1` and run the block below. Repeat with `$Sf = 10`, then
`$Sf = 100`. The block stops on an error. Each scale generates, loads, checks
correctness, and measures before moving on. Leave other benchmarks and heavy
applications idle during measurements.

```powershell
$Sf = 1                         # Change to 10, then 100 on the next runs
$Experiment = "desktop-9800x3d"  # Use the same value for all three
$Raw = "$Experiment-raw-sf$Sf"
$Container = "$Experiment-sf$Sf"
$Validation = "local/$Experiment/sf$Sf-validation"
$Run = "runs/$Experiment/sf$Sf"

python manage.py generate --sf $Sf --volume-only --volume-name $Raw
if ($LASTEXITCODE -ne 0) { throw "Data generation failed" }

python prepare_volume.py --data-volume $Raw --sf $Sf --name $Container
if ($LASTEXITCODE -ne 0) { throw "ClickHouse loading failed" }

$ValidationArgs = @()
if ($Sf -gt 1) {
    python validate_results.py --data-volume $Raw --container $Container --sf $Sf --output $Validation --stop-clickhouse-during-reference
    if ($LASTEXITCODE -ne 0) { throw "Correctness validation failed" }
    $ValidationArgs = @("--validation-dir", $Validation)
}

docker stop --timeout 10 $Container
if ($LASTEXITCODE -ne 0) { throw "Could not stop ClickHouse before benchmark restart" }
docker start $Container
if ($LASTEXITCODE -ne 0) { throw "Could not restart ClickHouse for benchmarking" }
try {
    python run_controlled.py --container $Container --sf $Sf --output $Run @ValidationArgs
    if ($LASTEXITCODE -ne 0) { throw "Benchmark did not finish. Check $Run/manifest.json" }
} finally {
    docker stop --timeout 10 $Container
}
```

SF1 must match the saved raw-file hashes and known query outputs. SF10 and
SF100 compare all 24 table counts and six query outputs against DuckDB using
the identical raw files. The benchmark checks the first warm-up results at
every scale.

ClickHouse uses 4 CPUs, an 8 GiB container limit, 4 query threads, a 6 GiB
query memory limit, and a 300-second query timeout at all three scales.
Each query gets 2 warm-ups and 7 measured attempts using the same schedule
and cache settings. Waiting up to 30 minutes for merges happens before timing.
The SF100 DuckDB reference runs separately while ClickHouse is stopped.

## 3. Collect and share

After all three runs finish, run this command from `milestone3`:

```powershell
python collect_results.py --sf1-run runs/desktop-9800x3d/sf1 --sf10-run runs/desktop-9800x3d/sf10 --sf100-run runs/desktop-9800x3d/sf100 --validation-dir local/desktop-9800x3d/sf10-validation --sf100-validation-dir local/desktop-9800x3d/sf100-validation --output results-desktop-9800x3d
```

Open `results-desktop-9800x3d/scaling_summary.csv`. It includes medians, failure
counts, and the ratios of SF10 and SF100 to SF1 for time, CPU, memory, and
logical reads. The output folder also holds per-run records and validation
evidence. Share that folder with the team. Raw data and database files stay
in Docker volumes.

## If a step fails

- After successful generation, a retry can reuse `$Raw` and start at loading.
  If generation itself failed, use a new raw volume name. For a failed import,
  use a fresh container name and stop the partial container before retrying.
- After successful loading, reuse the container for validation. Restart it
  if it is stopped. Use a new validation output directory for a retry.
  Inspect `validation.json` and `reference_report.json` for errors and
  comparisons. Preserve errors, including query timeouts and memory failures.
- If the benchmark times out waiting for merges, let ClickHouse settle and
  retry with a new `--output` directory. If a measured query fails, its attempt
  remains in the logs, and the collector leaves missing medians and ratios blank.
- If you change a measured resource limit, timeout, or other query setting,
  rerun all three scales under the new protocol and use those runs together.

The laptop runs have been measured. The SF100 workflow awaits execution on
the desktop.
