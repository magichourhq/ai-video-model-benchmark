#!/usr/bin/env python3
"""Build public tables, checksums, and visual review sheets from a completed run."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
rows = [json.loads(line) for line in (ROOT / "results.jsonl").read_text().splitlines()]
config = json.loads((ROOT / "benchmark.json").read_text())

if len(rows) != len(config["scenarios"]) * len(config["models"]) * config["attempts_per_model_scenario"]:
    raise SystemExit("Result count does not match the frozen benchmark matrix")

fields = sorted({key for row in rows for key in row})
with (ROOT / "results.csv").open("w", newline="") as output:
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)

by_model = defaultdict(list)
for row in rows:
    by_model[row["model"]].append(row)

summary = {
    "benchmark_id": config["benchmark_id"],
    "attempts": len(rows),
    "completed_outputs": sum(row["status"] == "complete" for row in rows),
    "failed_outputs": sum(row["status"] != "complete" for row in rows),
    "models": {},
}
for model in config["models"]:
    model_rows = by_model[model]
    completed = [row for row in model_rows if row["status"] == "complete"]
    summary["models"][model] = {
        "attempts": len(model_rows),
        "completed": len(completed),
        "failed": len(model_rows) - len(completed),
        "api_completion_rate": round(len(completed) / len(model_rows), 4),
        "total_credits_charged": sum(row.get("credits_charged") or 0 for row in model_rows),
        "median_credits_per_completed_output": statistics.median(
            row["credits_charged"] for row in completed
        ) if completed else None,
        "status_counts": dict(Counter(row["status"] for row in model_rows)),
    }
(ROOT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

row_by_key = {(row["scenario_id"], row["model"], row["attempt"]): row for row in rows}
gallery = [
    "# Output gallery",
    "",
    "Every link below is one independently requested eight-second, 720p output. Failed attempts remain visible in the table and in the result data.",
    "",
]
for scenario in config["scenarios"]:
    gallery += [
        f"## {scenario['buyer_use_case']}",
        "",
        f"![{scenario['id']} input](assets/inputs/{scenario['id']}.png)",
        "",
        f"![{scenario['id']} contact sheet](contact-sheets/{scenario['id']}.jpg)",
        "",
        "| Model | Attempt 1 | Attempt 2 | Attempt 3 |",
        "| --- | --- | --- | --- |",
    ]
    for model in config["models"]:
        cells = []
        for attempt in range(1, config["attempts_per_model_scenario"] + 1):
            row = row_by_key[(scenario["id"], model, attempt)]
            cells.append(f"[MP4]({row['public_path']})" if row["status"] == "complete" else "Failed, refunded")
        gallery.append(f"| {model} | " + " | ".join(cells) + " |")
    gallery.append("")
(ROOT / "GALLERY.md").write_text("\n".join(gallery))

sheet_dir = ROOT / "contact-sheets"
sheet_dir.mkdir(exist_ok=True)
for scenario in config["scenarios"]:
    inputs = ["-loop", "1", "-t", "1", "-i", str(ROOT / "assets" / "inputs" / f"{scenario['id']}.png")]
    labels = ["INPUT"]
    for model in config["models"]:
        for attempt in range(1, config["attempts_per_model_scenario"] + 1):
            row = row_by_key[(scenario["id"], model, attempt)]
            if row["status"] == "complete":
                inputs += ["-ss", "4", "-i", str(ROOT / row["public_path"])]
            else:
                inputs += ["-f", "lavfi", "-i", "color=c=1d1d1d:s=1280x720:d=1"]
            labels.append(f"{model} #{attempt}" + (" FAILED" if row["status"] != "complete" else ""))

    filters = []
    for index, label in enumerate(labels):
        escaped = label.replace(":", "\\:").replace("'", "\\'")
        filters.append(
            f"[{index}:v]scale=320:180:force_original_aspect_ratio=decrease,"
            f"pad=320:180:(ow-iw)/2:(oh-ih)/2:black,"
            f"drawbox=x=0:y=0:w=iw:h=28:color=black@0.65:t=fill,"
            f"drawtext=text='{escaped}':x=8:y=6:fontsize=16:fontcolor=white[v{index}]"
        )
    layout = "|".join(f"{(index % 4) * 320}_{(index // 4) * 180}" for index in range(16))
    filters.append("".join(f"[v{index}]" for index in range(16)) + f"xstack=inputs=16:layout={layout}[out]")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "1", str(sheet_dir / f"{scenario['id']}.jpg")],
        check=True,
    )

checksum_paths = [
    path for path in ROOT.rglob("*")
    if path.is_file() and path.name not in {"SHA256SUMS", "private-run-state.json"} and ".git" not in path.parts
]
with (ROOT / "SHA256SUMS").open("w") as output:
    for path in sorted(checksum_paths):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        output.write(f"{digest}  {path.relative_to(ROOT)}\n")
