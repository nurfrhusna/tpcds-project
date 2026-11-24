import argparse
import csv
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUMMARY = ROOT / "milestone3" / "results" / "scaling_summary.csv"
DEFAULT_OUT = ROOT / "tpc-ds" / "figures"

COLORS = ["#86b6ef", "#2a78d6", "#104281"]  # one hue, light to dark, because scale factors are ordered

METRICS = [
    ("server_duration_ms", "Median runtime (ms)", "runtime", 1, True),
    ("query_memory_bytes", "Median query memory (MiB)", "memory", 1 / 1048576, False),
    ("query_cpu_seconds", "Median CPU time (s)", "cpu_time", 1, True),
    ("read_bytes", "Median logical reads (MiB)", "logical_reads", 1 / 1048576, True),
]


def fmt(v):
    return f"{v:,.0f}" if v >= 10 else f"{v:.2g}"


def load(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    scales = sorted(
        {int(m.group(1)) for k in rows[0] for m in [re.match(r"sf(\d+)_server_duration_ms$", k)] if m}
    )
    return rows, scales


def grouped_bars(rows, scales, key, label, name, factor, log, out, title_note):
    queries = [f"Q{r['query']}" for r in rows]
    width = 0.8 / len(scales)
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    for i, sf in enumerate(scales):
        values = [float(r[f"sf{sf}_{key}"]) * factor for r in rows]
        xs = [x + (i - (len(scales) - 1) / 2) * width for x in range(len(rows))]
        bars = ax.bar(xs, values, width, label=f"SF{sf}", color=COLORS[i % len(COLORS)])
        ax.bar_label(bars, labels=[fmt(v) for v in values], fontsize=7, padding=2)
    ax.set_xticks(range(len(rows)), queries)
    ax.set_ylabel(label + (" (log scale)" if log else ""))
    if log:
        ax.set_yscale("log")
    ax.set_title(f"{label.split(' (')[0]} by query{title_note}")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / f"{name}.png")
    plt.close(fig)


def ratio_chart(rows, scales, out, title_note):
    queries = [f"Q{r['query']}" for r in rows]
    steps = list(zip(scales, scales[1:]))
    width = 0.8 / len(steps)
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    top = 0
    for i, (low, high) in enumerate(steps):
        ratios = [float(r[f"sf{high}_server_duration_ms"]) / float(r[f"sf{low}_server_duration_ms"]) for r in rows]
        top = max(top, *ratios, high / low)
        xs = [x + (i - (len(steps) - 1) / 2) * width for x in range(len(rows))]
        bars = ax.bar(xs, ratios, width, label=f"SF{low} to SF{high}", color=COLORS[(i + 1) % len(COLORS)])
        ax.bar_label(bars, fmt="%.1fx", fontsize=8, padding=2)
    growth = steps[0][1] / steps[0][0]
    ax.axhline(growth, color="#BBBBBB", linestyle="--", linewidth=1, zorder=0)
    ax.text(len(rows) - 0.5, growth, f" {growth:.0f}x", va="bottom", ha="right", fontsize=8, color="#555555")
    ax.set_ylim(0, top * 1.15)
    ax.set_xticks(range(len(rows)), queries)
    ax.set_ylabel("Runtime ratio")
    ax.set_title(f"Runtime growth for each {growth:.0f}x step in scale factor{title_note}")
    if len(steps) > 1:
        ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "runtime_ratio.png")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Plot Milestone 3 scaling results")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--note", default="", help="Text appended to chart titles, e.g. ' (laptop)'")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, scales = load(args.summary)
    for key, label, name, factor, log in METRICS:
        grouped_bars(rows, scales, key, label, name, factor, log, args.output, args.note)
    ratio_chart(rows, scales, args.output, args.note)
    print(f"Wrote {len(METRICS) + 1} charts for SF{', SF'.join(map(str, scales))} to {args.output}")


if __name__ == "__main__":
    main()
