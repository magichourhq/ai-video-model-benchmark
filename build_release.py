#!/usr/bin/env python3
"""Build public tables, checksums, and visual review sheets from a completed run."""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import secrets
import shutil
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def build_human_review(destination, media_root):
    """Prepare private blinded review and export only verified human aggregates."""
    destination = destination.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise SystemExit("Human review destination must be outside the repository")
    rubric_path = ROOT / "review-rubric.json"
    rubric = json.loads(rubric_path.read_text())
    rows = [json.loads(line) for line in (ROOT / "results.jsonl").read_text().splitlines()]
    config = json.loads((ROOT / "benchmark.json").read_text())
    expected = {(s["id"], m, a) for s in config["scenarios"] for m in config["models"]
                for a in range(1, config["attempts_per_model_scenario"] + 1)}
    actual = [(r["scenario_id"], r["model"], r["attempt"]) for r in rows]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise SystemExit("Attempts do not match the frozen matrix")
    if len({r["run_id"] for r in rows}) != len(rows):
        raise SystemExit("Duplicate run IDs")
    if any(r["benchmark_id"] != config["benchmark_id"] or
           not isinstance(r.get("credits_charged"), (int, float)) or
           isinstance(r["credits_charged"], bool) or
           not 0 <= r["credits_charged"] < float("inf") for r in rows):
        raise SystemExit("Missing or invalid benchmark identity/final customer charge")
    completed = [r for r in rows if r["status"] == "complete"]
    if any(r["status"] not in {"complete", "error"} for r in rows):
        raise SystemExit("Unresolved attempt state")
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in ["benchmark.json", "results.jsonl", "review-rubric.json"]}
    # Verify the bytes before copying any public source media into the blind packet.
    for r in rows:
        paths = [(r["input_path"], r["input_sha256"])]
        if r["status"] == "complete":
            paths.append((r["public_path"], r["sha256"]))
        for relative, expected_hash in paths:
            if hashlib.sha256((media_root / relative).read_bytes()).hexdigest() != expected_hash:
                raise SystemExit(f"Source media hash mismatch: {relative}")
    destination.mkdir(parents=True, exist_ok=True)
    private_path = destination / "private-randomization.json"
    if private_path.exists():
        private = json.loads(private_path.read_text())
        if private["input_hashes"] != hashes:
            raise SystemExit("Registered input/rubric changed; use a new edition directory")
    else:
        shuffled = completed.copy()
        secrets.SystemRandom().shuffle(shuffled)
        private = {"edition_id": "mh-i2v-commercial-v1-human-retrospective-1",
                   "registered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "input_hashes": hashes,
                   "assignment": [{"clip_key": secrets.token_hex(12), "run_id": r["run_id"],
                                   "sha256": r["sha256"]} for r in shuffled]}
        with private_path.open("x") as output:
            private_path.chmod(0o600)
            json.dump(private, output, indent=2)
            output.write("\n")
    assignment = private["assignment"]
    by_run = {r["run_id"]: r for r in completed}
    by_clip = {a["clip_key"]: by_run.get(a["run_id"]) for a in assignment}
    if (len(by_clip) != len(completed) or len(assignment) != len(completed) or
        {a["run_id"] for a in assignment} != set(by_run) or
        any(a["sha256"] != by_run[a["run_id"]]["sha256"] for a in assignment)):
        raise SystemExit("Private assignment does not match exact completed outputs")
    reviewers = ["R1", "R2", "R3"]
    dimensions = rubric["dimensions"]
    fields = ["clip_key", "reviewer", "rubric_version", *dimensions, "accepted", "reason", "reviewed_at"]
    packet = destination / "blind-packet"
    (packet / "clips").mkdir(parents=True, exist_ok=True)
    (packet / "inputs").mkdir(exist_ok=True)
    shutil.copyfile(rubric_path, packet / "rubric.json")
    review_page = ["# Blinded human review", "",
                   "Watch each complete clip against its input and motion brief. Score independently before discussion.",
                   "Do not inspect the original public dataset or private randomization key. Record any prior recognition.", ""]
    scenarios = {s["id"]: s for s in config["scenarios"]}
    for a in assignment:
        r = by_run[a["run_id"]]
        clip_path = packet / "clips" / f"{a['clip_key']}.mp4"
        if not clip_path.exists():
            shutil.copyfile(media_root / r["public_path"], clip_path)
        if hashlib.sha256(clip_path.read_bytes()).hexdigest() != a["sha256"]:
            raise SystemExit("Blinded clip bytes changed")
        input_name = f"{r['scenario_id']}.png"
        shutil.copyfile(media_root / r["input_path"], packet / "inputs" / input_name)
        review_page += [f"## {a['clip_key']}", "", f"![Input](inputs/{input_name})", "",
                        scenarios[r["scenario_id"]]["motion_prompt"], "",
                        "Format brief: eight seconds, 720p landscape, no requested audio.", "",
                        f"[Watch full clip](clips/{a['clip_key']}.mp4)", ""]
    (packet / "REVIEW.md").write_text("\n".join(review_page))
    ratings_path = destination / "ratings.csv"
    if not ratings_path.exists():
        with ratings_path.open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows({"clip_key": a["clip_key"], "reviewer": reviewer,
                              "rubric_version": rubric["version"]}
                             for a in assignment for reviewer in reviewers)
    roster_path = destination / "reviewers.csv"
    if not roster_path.exists():
        with roster_path.open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["reviewer", "affiliation", "independent", "prior_recognition"], lineterminator="\n")
            writer.writeheader()
            writer.writerows({"reviewer": reviewer} for reviewer in reviewers)
    with ratings_path.open(newline="") as source:
        labels = list(csv.DictReader(source))
    seen = set()
    scored = {}
    for label in labels:
        key = (label["clip_key"], label["reviewer"])
        if (key in seen or key[0] not in by_clip or key[1] not in reviewers or
            label["rubric_version"] != rubric["version"]):
            raise SystemExit("Duplicate/unknown clip, reviewer or rubric")
        seen.add(key)
        if not any(label.get(f) for f in [*dimensions, "accepted", "reason", "reviewed_at"]):
            continue
        if any(label.get(d) not in {"pass", "minor", "block"} for d in dimensions):
            raise SystemExit("Incomplete or invalid dimension rating")
        accepted = not any(label[d] == "block" for d in dimensions)
        if label.get("accepted") != ("yes" if accepted else "no") or not label.get("reason", "").strip():
            raise SystemExit("Acceptance conflicts with rubric or missing review reason")
        try:
            timestamp = datetime.datetime.fromisoformat(label["reviewed_at"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError()
        except (ValueError, KeyError):
            raise SystemExit("Review timestamp must include timezone")
        if timestamp < datetime.datetime.fromisoformat(private["registered_at"]):
            raise SystemExit("Rating predates rubric registration")
        scored[key] = accepted
    with roster_path.open(newline="") as source:
        roster = list(csv.DictReader(source))
    if len({r["reviewer"] for r in roster}) != len(roster) or any(r["reviewer"] not in reviewers for r in roster):
        raise SystemExit("Duplicate/unknown reviewer disclosure")
    disclosed = (set(r["reviewer"] for r in roster) == set(reviewers) and
                 all(r.get("affiliation", "").strip() and r.get("prior_recognition", "").strip()
                     and r.get("independent") in {"yes", "no"} for r in roster) and
                 any(r.get("independent") == "yes" for r in roster))
    ready = len(scored) == len(completed) * 3 and disclosed
    summary = {"edition_id": private["edition_id"], "status": "scored" if ready else "unscored",
               "attempts": len(rows), "completed": len(completed), "ratings_received": len(scored),
               "ratings_required": len(completed) * 3, "reviewer_disclosures_complete": disclosed,
               "input_image_generation_cost": "not recorded; excluded", "models": {}}
    for model in config["models"]:
        attempts = [r for r in rows if r["model"] == model]
        done = [r for r in attempts if r["status"] == "complete"]
        metrics = {"attempts": len(attempts), "completed": len(done),
                   "technical_completion": len(done) / len(attempts),
                   "final_customer_credits": sum(r["credits_charged"] for r in attempts)}
        if ready:
            accepted_count = sum(sum(scored[(a["clip_key"], reviewer)] for reviewer in reviewers) >= 2
                                 for a in assignment if by_run[a["run_id"]]["model"] == model)
            metrics.update(accepted=accepted_count, acceptance_yield=accepted_count / len(attempts),
                           acceptance_among_completed=accepted_count / len(done) if done else None,
                           credits_per_accepted_clip=metrics["final_customer_credits"] / accepted_count if accepted_count else None)
        summary["models"][model] = metrics
    public = destination / "public"
    public.mkdir(exist_ok=True)
    (public / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    registration = {k: v for k, v in private.items() if k != "assignment"}
    registration.update(parent_version="v1.0.0", retrospective=True, rubric_version=rubric["version"],
                        assignment_sha256=hashlib.sha256(private_path.read_bytes()).hexdigest())
    (public / "registration.json").write_text(json.dumps(registration, indent=2, sort_keys=True) + "\n")
    shutil.copyfile(rubric_path, public / "rubric.json")
    shutil.copyfile(ROOT / "HUMAN_REVIEW.md", public / "DATA_DICTIONARY.md")
    with (public / "all-attempts.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["run_id", "scenario_id", "model", "attempt", "status", "credits_charged", "sha256"], extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (public / "summary.csv").open("w", newline="") as output:
        model_fields = sorted({key for metrics in summary["models"].values() for key in metrics})
        writer = csv.DictWriter(output, fieldnames=["model", *model_fields], lineterminator="\n")
        writer.writeheader()
        writer.writerows({"model": model, **metrics} for model, metrics in summary["models"].items())
    names = ["summary.json", "summary.csv", "registration.json", "rubric.json", "DATA_DICTIONARY.md", "all-attempts.csv"]
    if ready:
        for source in [ratings_path, roster_path]:
            shutil.copyfile(source, public / source.name)
            names.append(source.name)
        (public / "unblinding-key.json").write_text(json.dumps(assignment, indent=2) + "\n")
        names.append("unblinding-key.json")
    else:
        for name in ["ratings.csv", "reviewers.csv", "unblinding-key.json"]:
            (public / name).unlink(missing_ok=True)
    manifest = {name: hashlib.sha256((public / name).read_bytes()).hexdigest() for name in names}
    (public / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"destination": str(destination), "status": summary["status"],
                      "completed": len(completed), "ratings_received": len(scored),
                      "publication_allowlist": [*names, "manifest.json"]}))


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--human-review", type=Path, help="Private edition directory outside the repository")
parser.add_argument("--media-root", type=Path, default=ROOT, help="Directory containing unchanged public assets")
args = parser.parse_args()
if args.human_review:
    build_human_review(args.human_review, args.media_root.resolve())
    raise SystemExit(0)

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
