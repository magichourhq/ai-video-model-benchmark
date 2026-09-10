#!/usr/bin/env python3
"""Create and collect a resumable Magic Hour commercial image-to-video benchmark."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "benchmark.json"
STATE_PATH = ROOT / "private-run-state.json"
RESULTS_PATH = ROOT / "results.jsonl"
ASSETS_DIR = ROOT / "assets"
API_BASE = "https://api.magichour.ai/v1"
TERMINAL = {"complete", "error", "canceled"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def request_json(method: str, path: str, token: str, body=None):
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=payload,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Magic-Hour-Public-Benchmark/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {error.code}: {detail[:500]}") from error


def poll_project(kind: str, project_id: str, token: str):
    while True:
        project = request_json("GET", f"/{kind}-projects/{project_id}", token)
        if project["status"] in TERMINAL:
            return project
        time.sleep(10)


def download(url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Magic-Hour-Public-Benchmark/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def generate_inputs(config, state, token: str) -> None:
    state.setdefault("inputs", {})
    for scenario in config["scenarios"]:
        scenario_id = scenario["id"]
        entry = state["inputs"].setdefault(scenario_id, {})
        if "project_id" not in entry:
            body = {
                "name": f"Public benchmark input - {scenario_id}",
                "image_count": 1,
                "model": config["input_image_model"],
                "aspect_ratio": "16:9",
                "resolution": "1k",
                "style": {"prompt": scenario["input_prompt"], "tool": "ai-photo-generator"},
            }
            started = time.time()
            created = request_json("POST", "/ai-image-generator", token, body)
            entry.update({"project_id": created["id"], "submitted_at": now(), "request": body, "started_epoch": started})
            save_json(STATE_PATH, state)
        completed = poll_project("image", entry["project_id"], token)
        entry.update({
            "status": completed["status"],
            "credits_charged": completed.get("credits_charged"),
            "completed_at": now(),
            "elapsed_seconds": round(time.time() - entry["started_epoch"], 3),
            "error": completed.get("error"),
        })
        if completed["status"] != "complete":
            save_json(STATE_PATH, state)
            raise RuntimeError(f"Input generation failed for {scenario_id}: {completed.get('error')}")
        destination = ASSETS_DIR / "inputs" / f"{scenario_id}.png"
        entry["download_url"] = completed["downloads"][0]["url"]
        entry["sha256"] = download(entry["download_url"], destination)
        entry["public_path"] = str(destination.relative_to(ROOT))
        save_json(STATE_PATH, state)
        print(f"input complete: {scenario_id}", flush=True)


def generate_videos(config, state, token: str) -> None:
    state.setdefault("runs", {})
    planned = []
    for scenario in config["scenarios"]:
        input_entry = state["inputs"][scenario["id"]]
        for model in config["models"]:
            for attempt in range(1, config["attempts_per_model_scenario"] + 1):
                run_id = f"{scenario['id']}--{model}--{attempt:02d}"
                entry = state["runs"].setdefault(run_id, {})
                if entry.get("status") == "complete" and entry.get("sha256"):
                    continue
                planned.append((scenario, model, attempt, run_id, entry, input_entry))
                if "project_id" not in entry:
                    body = {
                        "name": f"Public benchmark - {run_id}",
                        "end_seconds": config["duration_seconds"],
                        "model": model,
                        "resolution": config["resolution"],
                        "audio": config["audio"],
                        "assets": {"image_file_path": input_entry["download_url"]},
                        "style": {"prompt": scenario["motion_prompt"]},
                    }
                    started = time.time()
                    created = request_json("POST", "/image-to-video", token, body)
                    entry.update({
                        "run_id": run_id,
                        "scenario_id": scenario["id"],
                        "buyer_use_case": scenario["buyer_use_case"],
                        "model": model,
                        "attempt": attempt,
                        "project_id": created["id"],
                        "submitted_at": now(),
                        "request": body,
                        "started_epoch": started,
                    })
                    save_json(STATE_PATH, state)
                    print(f"submitted: {run_id}", flush=True)
                    time.sleep(0.5)

    for scenario, model, attempt, run_id, entry, input_entry in planned:
        if entry.get("status") == "complete" and entry.get("sha256"):
            continue
        completed = poll_project("video", entry["project_id"], token)
        entry.update({
            "status": completed["status"],
            "credits_charged": completed.get("credits_charged"),
            "completed_at": now(),
            "elapsed_seconds": round(time.time() - entry["started_epoch"], 3),
            "width": completed.get("width"),
            "height": completed.get("height"),
            "fps": completed.get("fps"),
            "error": completed.get("error"),
        })
        if completed["status"] == "complete":
            destination = ASSETS_DIR / "outputs" / scenario["id"] / model / f"attempt-{attempt:02d}.mp4"
            entry["sha256"] = download(completed["downloads"][0]["url"], destination)
            entry["public_path"] = str(destination.relative_to(ROOT))
        save_json(STATE_PATH, state)
        print(f"{completed['status']}: {run_id}", flush=True)


def export_results(config, state) -> None:
    with RESULTS_PATH.open("w") as output:
        for run_id in sorted(state.get("runs", {})):
            entry = state["runs"][run_id]
            public = {key: value for key, value in entry.items() if key not in {"project_id", "request", "started_epoch"}}
            public["observed_terminal_seconds_upper_bound"] = public.pop("elapsed_seconds", None)
            public["benchmark_id"] = config["benchmark_id"]
            public["input_path"] = state["inputs"][entry["scenario_id"]].get("public_path")
            public["input_sha256"] = state["inputs"][entry["scenario_id"]].get("sha256")
            output.write(json.dumps(public, sort_keys=True) + "\n")


def main() -> int:
    token = os.environ.get("MAGIC_HOUR_API_KEY")
    if not token:
        print("MAGIC_HOUR_API_KEY is required", file=sys.stderr)
        return 2
    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"benchmark_id": config["benchmark_id"], "created_at": now()})
    generate_inputs(config, state, token)
    generate_videos(config, state, token)
    export_results(config, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
