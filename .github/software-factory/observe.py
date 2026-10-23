"""Observe trusted Actions metadata without reading candidate artifacts or model output."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

PATHS = {"implement": "software-factory-implement.yml", "final-review": "final-review.yml"}
STATES = {"queued", "in_progress", "success", "failure", "cancelled", "skipped", "timed_out", "neutral", "action_required"}
JOBS = {"gate", "gate-feedback", "claim", "handoff", "retro", "retro-publish", "report",
        "identify", "review", "publish"} | {f"round{n} / {stage}" for n in range(1, 5)
                                                   for stage in ("implement", "verify", "review", "diagnostics")}
SHA = re.compile(r"[0-9a-f]{40}")


def get(path):
    return json.loads(subprocess.check_output(["gh", "api", path], stderr=subprocess.DEVNULL))


def pages(api, path, key):
    result = []
    for page in range(1, 4):
        items = api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")[key]
        result.extend(items)
        if len(items) < 100:
            break
    return result


def identity(run, repo):
    owner = repo.split('/')[0]
    if (run.get("head_repository", {}).get("full_name") != repo or run.get("head_branch") != "main"):
        return None
    actors = [run.get(key, {}).get("login") for key in ("actor", "triggering_actor")]
    for kind, filename in PATHS.items():
        if run.get("path") != f".github/workflows/{filename}":
            continue
        if kind == "implement":
            match = re.fullmatch(r"Factory issue #([1-9][0-9]*) · attempt [1-9][0-9]*", run.get("display_title", ""))
            if match and actors == [owner, owner] and run.get("event") in ("issues", "workflow_dispatch"):
                return kind, match[1], None
        else:
            match = re.fullmatch(r"Final PR #([1-9][0-9]*) · parent (none|[1-9][0-9]*\.[1-9][0-9]*)", run.get("display_title", ""))
            if (match and all(actor in (owner, "github-actions[bot]") for actor in actors)
                    and run.get("event") in ("pull_request_target", "workflow_dispatch")):
                return kind, match[1], None if match[2] == "none" else match[2]
    return None


def summarize_jobs(jobs, kind):
    safe = {}
    for job in jobs:
        name = job.get("name")
        if name in JOBS:
            state = job.get("conclusion") or job.get("status")
            safe[name] = state if state in STATES else "unavailable"
    active = [name for name, state in safe.items() if state == "in_progress"]
    return {"jobs": safe, "phase": active[-1] if active else "waiting-or-completed",
            "delivery": safe.get("handoff", "pending") if kind == "implement" else "separate-implementation-run",
            "final_review": "pending-separate-run" if kind == "implement" else safe.get("publish", "pending"),
            "retro": safe.get("retro-publish", safe.get("retro", "pending")) if kind == "implement" else "separate-implementation-run",
            "ci": "unavailable-inspect-pr-checks"}


def snapshot(api, repo, run_id):
    prefix = f"repos/{repo}"
    run = api(f"{prefix}/actions/runs/{run_id}")
    ident = identity(run, repo)
    if not ident:
        return None
    kind, number, parent = ident
    workflow = api(f"{prefix}/actions/workflows/{PATHS[kind]}")
    if run.get("workflow_id") != workflow["id"]:
        return None
    target = api(f"{prefix}/{'issues' if kind == 'implement' else 'pulls'}/{number}")
    owner = repo.split('/')[0]
    if kind == "implement":
        if "pull_request" in target or target.get("user", {}).get("login") != owner:
            return None
        branch = f"feat/{number}-implement"
    else:
        if (target.get("head", {}).get("repo", {}).get("full_name") != repo
                or target.get("base", {}).get("repo", {}).get("full_name") != repo
                or target.get("base", {}).get("ref") != "main"
                or target.get("user", {}).get("login") not in (owner, "github-actions[bot]")):
            return None
        branch = target["head"].get("ref", "")
        if not parent and any(run.get(key, {}).get("login") == "github-actions[bot]" for key in ("actor", "triggering_actor")):
            return None
        if parent:
            parent_id, attempt = parent.split('.')
            source = api(f"{prefix}/actions/runs/{parent_id}/attempts/{attempt}")
            current = api(f"{prefix}/actions/runs/{parent_id}")
            source_identity = identity(source, repo)
            source_workflow = api(f"{prefix}/actions/workflows/{PATHS['implement']}")
            if (not source_identity or source_identity[0] != "implement"
                    or source.get("workflow_id") != source_workflow["id"]
                    or source.get("run_attempt") != int(attempt)
                    or current.get("run_attempt") != int(attempt)
                    or branch != f"feat/{source_identity[1]}-implement"):
                return None
            source_jobs = pages(api, f"{prefix}/actions/runs/{parent_id}/attempts/{attempt}/jobs", "jobs")
            if not any(job.get("name") == "handoff" and job.get("conclusion") == "success" for job in source_jobs):
                return None
    attempt = int(run["run_attempt"])
    jobs = pages(api, f"{prefix}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    if kind == "implement" and not any(job.get("name") == "gate" and job.get("status") != "queued"
                                        and job.get("conclusion") != "skipped" for job in jobs):
        return None
    status = run.get("conclusion") or run.get("status")
    head = target.get("head", {}).get("sha") if kind == "final-review" else run.get("head_sha")
    result = {"schema": 1, "repository": repo, "run_id": int(run_id), "run_attempt": attempt,
              "kind": kind, "issue": int(number) if kind == "implement" else None,
              "pr": int(number) if kind == "final-review" else None, "parent": parent,
              "branch": branch if re.fullmatch(r"[A-Za-z0-9/_.-]{1,200}", branch) else "unavailable",
              "head": head if isinstance(head, str) and SHA.fullmatch(head) else None,
              "base": target.get("base", {}).get("sha") if kind == "final-review" else None,
              "state": status if status in STATES else "unavailable",
              "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "started_at": run.get("run_started_at"), "completed_at": run.get("updated_at") if run.get("status") == "completed" else None,
              "reason": "actions-metadata", "evidence": {"run": f"https://github.com/{repo}/actions/runs/{run_id}/attempts/{attempt}"},
              **summarize_jobs(jobs, kind)}
    if kind == "implement":
        pulls = api(f"{prefix}/pulls?state=all&head={owner}:feat/{number}-implement&per_page=20")
        pulls = [pr for pr in pulls if pr.get("head", {}).get("repo", {}).get("full_name") == repo
                 and pr.get("base", {}).get("ref") == "main"]
        if pulls:
            result["pr"] = int(pulls[0]["number"])
            result["head"] = pulls[0]["head"]["sha"]
    if parent:
        parent_id, parent_attempt = parent.split('.')
        result["evidence"]["parent"] = f"https://github.com/{repo}/actions/runs/{parent_id}/attempts/{parent_attempt}"
    if result["pr"]:
        result["evidence"]["pr"] = f"https://github.com/{repo}/pull/{result['pr']}"
    result["evidence"]["jobs"] = f"https://github.com/{repo}/actions/runs/{run_id}/jobs"
    artifacts = pages(api, f"{prefix}/actions/runs/{run_id}/artifacts", "artifacts")
    result["artifacts"] = [{"id": item["id"], "expired": item.get("expired") is True}
                           for item in artifacts if type(item.get("id")) is int]
    result["evidence_state"] = "recorded" if result["artifacts"] else "unavailable-not-proof-never-produced"
    result["next_action"] = ("Observe progress in Actions; no retry is authorized." if status in ("queued", "in_progress") else
                             "Inspect delivery, final review, retro and PR checks separately; human acceptance and merge remain required.")
    return result


def render(record):
    lines = [f"Factory {record['kind']}: **{record['state']}**; phase: {record['phase']}.",
             f"Execution: {record['run_id']}.{record['run_attempt']}; parent: {record['parent'] or 'none'}.",
             f"Delivery: {record['delivery']}; independent final review: {record['final_review']}; retro: {record['retro']}; CI: {record['ci']}."]
    lines.extend(f"{name}: {state}." for name, state in record["jobs"].items())
    lines.extend([f"Next action: {record['next_action']}", "Evidence: " + " · ".join(record["evidence"].values()),
                  f"Artifact metadata: {record['evidence_state']}; expired recorded artifacts: {sum(item['expired'] for item in record['artifacts'])}.",
                  "Metadata only; missing evidence does not prove a stage never started. No retry, merge or deployment is performed."])
    return '\n\n'.join(lines)


def publish(record):
    repo, run_id = record["repository"], record["run_id"]
    target = record["issue"] or record["pr"]
    marker = f"<!-- factory-observation:{record['kind']}:{run_id} -->"
    body = marker + '\n' + render(record)
    comments = []
    for page in range(1, 4):
        items = get(f"repos/{repo}/issues/{target}/comments?per_page=100&page={page}")
        comments.extend(items)
        if len(items) < 100:
            break
    existing = next((item for item in comments if item.get("user", {}).get("login") == "github-actions[bot]"
                     and item.get("user", {}).get("type") == "Bot"
                     and (item.get("body") or '').split('\n', 1)[0] == marker), None)
    if existing and existing["body"] == body:
        return
    path = f"repos/{repo}/issues/comments/{existing['id']}" if existing else f"repos/{repo}/issues/{target}/comments"
    subprocess.run(["gh", "api", "--method", "PATCH" if existing else "POST", path, "--input", "-"],
                   input=json.dumps({"body": body}), text=True, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    run_id, output = sys.argv[1:]
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[1-9][0-9]*", run_id) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid-identity")
    # A completed-event observer is also allowed to repair a missed in-progress observer.
    previous = None
    for _ in range(300):
        record = snapshot(get, repo, run_id)
        if record is None:
            source = get(f"repos/{repo}/actions/runs/{run_id}")
            if identity(source, repo) and source.get("status") != "completed":
                time.sleep(60)
                continue
            print("Factory observation: unrelated or unauthorized run; summary only.")
            return
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(record, indent=2))
        body = render(record)
        if body != previous:
            publish(record)
            previous = body
        if record["state"] not in ("queued", "in_progress"):
            break
        time.sleep(60)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(render(record) + '\n')


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("::warning::factory-observation-unavailable; inspect source run")
        sys.exit(1)
