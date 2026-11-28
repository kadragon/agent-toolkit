"""Bounded, payload-free wall-clock measurements for a dispatch receipt."""

import json
import re
import time

MAX_LAUNCHES = 8
MAX_ATTEMPTS = 16  # per phase, per launch
HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
PHASES = ("review", "ci")
OUTCOMES = ("complete", "passed", "failed", "incomplete")


def now_ms():
    return time.time_ns() // 1_000_000


def elapsed(start, end):
    return end - start if start is not None and end is not None and end >= start else None


def empty_history():
    return {"launches": [], "dropped_launches": 0, "last_attempt": dict.fromkeys(PHASES, 0), "merge": None}


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return new_launch(empty_history(), None)


def new_launch(data, at):
    launches = data["launches"]
    previous = launches[-1] if launches else {}
    launches.append({
        "launched_ms": at, "delivered_ms": None, "closed_ms": None, "first_review_ms": None,
        "restart_ms": elapsed(previous.get("closed_ms"), at),
        "review": [], "ci": [], "dropped_review": 0, "dropped_ci": 0,
    })
    if len(launches) > MAX_LAUNCHES:
        launches.pop(0)
        data["dropped_launches"] += 1
    return data


def mark(data, field, at):
    launch = data["launches"][-1]
    if launch[field] is None:
        launch[field] = at


def start(data, phase, head, at):
    if not HEAD.fullmatch(head):
        raise ValueError("expected a full head SHA")
    launch = data["launches"][-1]
    if phase == "review":
        mark(data, "first_review_ms", at)
    attempts = launch[phase]
    attempt = data["last_attempt"][phase] + 1
    data["last_attempt"][phase] = attempt
    attempts.append({"attempt": attempt, "head": head, "started_ms": at,
                     "finished_ms": None, "outcome": None})
    if len(attempts) > MAX_ATTEMPTS:
        attempts.pop(0)
        launch[f"dropped_{phase}"] += 1
    return attempt


def finish(data, phase, attempt_id, outcome, at):
    attempt = next((entry for launch in reversed(data["launches"])
                    for entry in launch[phase] if entry["attempt"] == attempt_id), None)
    if attempt is None:
        if 0 < attempt_id <= data["last_attempt"][phase]:
            return  # Evicted while running.
        raise ValueError(f"unknown {phase} attempt {attempt_id}")
    if attempt["finished_ms"] is None:
        attempt.update(finished_ms=at, outcome=outcome)


def merged(data, head, at):
    if head is not None and not HEAD.fullmatch(head):
        raise ValueError("expected a full head SHA")
    if data["merge"] is None:
        data["merge"] = {"confirmed_ms": at, "head": head}
    elif data["merge"]["head"] is None:
        data["merge"]["head"] = head


def report(data, result):
    merge = data["merge"]
    head = merge["head"] if merge else (result or {}).get("head")
    final_head = head if isinstance(head, str) and HEAD.fullmatch(head) else None
    if merge:
        first_launch = None if data["dropped_launches"] else data["launches"][0]["launched_ms"]
        merge = {**merge, "elapsed_ms": elapsed(first_launch, merge["confirmed_ms"])}
    launches = []
    for launch in data["launches"]:
        measurements = {
            **launch,
            "startup_ms": elapsed(launch["launched_ms"], launch["delivered_ms"]),
            "implementation_ms": elapsed(launch["delivered_ms"], launch["first_review_ms"]),
        }
        for phase in PHASES:
            measurements[phase] = [
                {**entry, "elapsed_ms": elapsed(entry["started_ms"], entry["finished_ms"])}
                for entry in launch[phase]
            ]
        launches.append(measurements)
    return {"dropped_launches": data["dropped_launches"], "launches": launches,
            "merge": merge, "final_head": final_head}
