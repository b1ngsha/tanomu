"""Shared metadata vocabulary and observations; never authorizes GitHub writes."""
import re

WORKFLOWS = {"implementation": ("software-factory-implement.yml",),
             "final-review": ("agent-review.yml", "final-review.yml")}
FILES = {kind: filenames[0] for kind, filenames in WORKFLOWS.items()}
STATES = {"queued", "in_progress", "completed", "waiting", "pending", "requested"}
RESULTS = {"success", "failure", "cancelled", "skipped", "timed_out", "neutral", "action_required", "stale"}
SHA = re.compile(r"[0-9a-f]{40}")
# Retain metadata compatibility with historical four-round runs.
ROUNDS = range(1, 5)
ARTIFACTS = {"factory-input", "factory-claim", "final-input", "final-review"} | {
    f"{prefix}-{n}" for n in ROUNDS
    for prefix in ("session-implement", "session-review", "candidate", "checked", "feedback", "round-status")}
JOBS = {"gate", "gate-feedback", "claim", "handoff", "publish-reviews", "report",
        "identify", "review", "publish"} | {f"round{n} / {stage}" for n in ROUNDS
        for stage in ("implement", "verify", "review", "diagnostics")}


def state(value, choices, unknown="unknown"):
    return value if isinstance(value, str) and value in choices else unknown


def job_states(rows, names=None, unknown="unknown"):
    return {item.get("name"): state(item.get("conclusion") or item.get("status"), STATES | RESULTS, unknown)
            for item in rows if names is None or item.get("name") in names}


def publication_findings(kind, status, conclusion, jobs, complete):
    if status != "completed" or not complete:
        return []
    if kind in ("implement", "implementation"):
        # publish-reviews is scheduled only for claimed, non-cancelled runs.
        if jobs.get("claim") == "success" and conclusion != "cancelled" and jobs.get("publish-reviews") != "success":
            return ["round-reviews-not-delivered"]
    else:
        deduplicated = jobs.get("identify") == "success" and jobs.get("review") == "skipped" and jobs.get("publish") == "skipped"
        if jobs.get("publish") != "success" and not deduplicated:
            return ["final-review-not-delivered"]
    return []
