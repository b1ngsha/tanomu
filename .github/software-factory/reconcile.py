"""Bounded, read-only recovery observations; GitHub metadata is never an instruction."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess

FILES = {"implementation": "software-factory-implement.yml", "final-review": "final-review.yml"}
STATES = {"queued", "in_progress", "completed", "waiting", "pending", "requested"}
RESULTS = {"success", "failure", "cancelled", "skipped", "timed_out", "neutral", "action_required", "stale"}
ARTIFACTS = {"factory-input", "factory-claim", "final-input", "final-review"}
NUMBER = r"[1-9][0-9]{0,19}"
ISSUE = re.compile(rf"Factory issue #({NUMBER}) · attempt ({NUMBER})")
CHILD = re.compile(rf"Final PR #({NUMBER}) · parent ({NUMBER})\.({NUMBER})")
STANDALONE = re.compile(rf"Final PR #({NUMBER}) · parent none")
ACTIONS = {"stale-implementation": "Inspect queued/running jobs; owner may cancel or rerun after diagnosis.",
           "stale-implementing-label": "Owner should inspect delivery before manually correcting the issue state.",
           "final-review-not-observed": "Owner should inspect the handoff and dispatch a final review if needed.",
           "final-review-not-delivered": "Owner should inspect final review publish before manually rerunning it.",
           "evidence-expired": "Recorded evidence expired; inspect retained job metadata and request a fresh run if needed."}
SHA = re.compile(r"[0-9a-f]{40}")


def integer(value):
    return int(str(value)) if re.fullmatch(NUMBER, str(value)) else None


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def state(value, choices):
    return value if isinstance(value, str) and value in choices else "unknown"


class Reader:
    def __init__(self, api, repo):
        self.api, self.root, self.notices = api, f"repos/{repo}", set()
        self.requests = 0

    def get(self, path):
        if self.requests >= 300:
            self.notices.add("request-budget-exhausted")
            return None
        self.requests += 1
        try:
            return self.api(f"{self.root}/{path}")
        except Exception:
            self.notices.add("api-partial-failure")
            return None

    def pages(self, path, key, limit=3):
        rows, complete = [], False
        for page in range(1, limit + 1):
            data = self.get(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                self.notices.add("metadata-unavailable")
                return rows, False
            batch = data[key][:100]
            rows.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                complete = True
                break
        if not complete:
            self.notices.add(f"{key}-scan-limited")
        return rows, complete


def trusted(run, workflow, repo, kind):
    owner = repo.split("/")[0]
    actors = {owner} if kind == "implementation" else {owner, "github-actions[bot]"}
    return (integer(run.get("id")) is not None and integer(run.get("run_attempt")) is not None
            and run.get("workflow_id") == workflow.get("id")
            and run.get("path") == f".github/workflows/{FILES[kind]}"
            and run.get("head_repository", {}).get("full_name") == repo
            and run.get("head_branch") == "main"
            and run.get("event") in ({"workflow_dispatch", "issues"} if kind == "implementation"
                                     else {"workflow_dispatch", "pull_request_target"})
            and run.get("actor", {}).get("login") in actors
            and run.get("triggering_actor", {}).get("login") in actors)


def jobs(reader, run):
    rows, complete = reader.pages(
        f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
    return {item.get("name"): state(item.get("conclusion"), RESULTS) for item in rows}, complete


def artifacts(reader, run):
    rows, complete = reader.pages(f"actions/runs/{run['id']}/artifacts", "artifacts", 1)
    return {name: (["recorded-expired" if row.get("expired") is True else "recorded"
                    for row in rows if row.get("name") == name] or ["absent-unknown"])
            for name in sorted(ARTIFACTS)}, complete


def pr_status(reader, repo, issue):
    owner = repo.split("/")[0]
    data = reader.get(f"pulls?state=all&head={owner}:feat/{issue}-implement&per_page=100")
    if not isinstance(data, list):
        return None
    matches = [pr for pr in data[:100] if integer(pr.get("number"))
               and pr.get("head", {}).get("ref") == f"feat/{issue}-implement"
               and pr.get("head", {}).get("repo", {}).get("full_name") == repo
               and pr.get("base", {}).get("repo", {}).get("full_name") == repo
               and pr.get("base", {}).get("ref") == "main"]
    if len(matches) != 1:
        return None
    detail = reader.get(f"pulls/{matches[0]['number']}")
    if not isinstance(detail, dict) or detail.get("number") != matches[0]["number"]:
        return None
    return detail if (detail.get("head", {}).get("ref") == f"feat/{issue}-implement"
                      and detail.get("head", {}).get("repo", {}).get("full_name") == repo
                      and detail.get("base", {}).get("repo", {}).get("full_name") == repo
                      and detail.get("base", {}).get("ref") == "main") else None


def deployment(reader, repo, pr):
    sha = pr.get("merge_commit_sha") if pr.get("merged") is True else None
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        return "unavailable"
    workflow = reader.get("actions/workflows/ci.yml")
    if not isinstance(workflow, dict) or not integer(workflow.get("id")) or workflow.get("path") != ".github/workflows/ci.yml":
        return "unavailable"
    rows, _ = reader.pages(f"actions/workflows/{workflow['id']}/runs?head_sha={sha}", "workflow_runs", 1)
    candidates = [run for run in rows if integer(run.get("id")) and integer(run.get("run_attempt"))
                  and run.get("head_sha") == sha and run.get("head_branch") == "main"
                  and run.get("event") == "push" and run.get("workflow_id") == workflow["id"]
                  and run.get("path") == workflow["path"]
                  and run.get("head_repository", {}).get("full_name") == repo]
    if not candidates:
        return "unavailable"
    latest = max(candidates, key=lambda run: (int(run["id"]), int(run["run_attempt"])))
    states, complete = jobs(reader, latest)
    if states.get("deploy") in RESULTS:
        return states["deploy"]
    return "pending" if complete and latest.get("status") != "completed" else "unavailable"


def checks(reader, repo, sha):
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        return "unavailable"
    workflow = reader.get("actions/workflows/ci.yml")
    if not isinstance(workflow, dict) or workflow.get("path") != ".github/workflows/ci.yml" or not integer(workflow.get("id")):
        return "unavailable"
    rows, complete = reader.pages(f"actions/workflows/{workflow['id']}/runs?head_sha={sha}", "workflow_runs", 1)
    matching = [run for run in rows if run.get("workflow_id") == workflow["id"]
                and run.get("path") == workflow["path"] and run.get("head_sha") == sha
                and run.get("head_repository", {}).get("full_name") == repo
                and run.get("event") in {"pull_request", "push"} and integer(run.get("id"))]
    if not complete or not matching:
        return "unavailable"
    latest = max(matching, key=lambda run: (int(run["id"]), integer(run.get("run_attempt")) or 0))
    if latest.get("status") != "completed":
        return "pending"
    conclusion = latest.get("conclusion")
    return conclusion if conclusion in {"success", "failure", "cancelled", "timed_out"} else "unavailable"


def reconcile(api, repo, now=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("invalid-repository")
    now = now or datetime.now(timezone.utc)
    reader, pools = Reader(api, repo), {}
    cutoff = now - timedelta(days=90)
    for kind, filename in FILES.items():
        workflow = reader.get(f"actions/workflows/{filename}")
        if not isinstance(workflow, dict) or not integer(workflow.get("id")) or workflow.get("path") != f".github/workflows/{filename}":
            reader.notices.add("workflow-unavailable")
            pools[kind] = []
            continue
        rows, _ = reader.pages(f"actions/workflows/{workflow['id']}/runs?created=%3E%3D{cutoff.date()}", "workflow_runs")
        pools[kind] = [run for run in rows if trusted(run, workflow, repo, kind)
                       and instant(run.get("created_at")) and cutoff <= instant(run["created_at"]) <= now]
        if len(pools[kind]) > 20:
            reader.notices.add("run-detail-limited")
    parent_keys = {(int(run["id"]), int(run["run_attempt"])) for run in pools["implementation"]}
    # A bot dispatch needs an observed owner-authenticated implementation parent.
    pools["final-review"] = [run for run in pools["final-review"]
        if (run.get("actor", {}).get("login") == repo.split("/")[0]
            and run.get("triggering_actor", {}).get("login") == repo.split("/")[0])
        or (run.get("event") == "workflow_dispatch"
            and CHILD.fullmatch(run.get("display_title", ""))
            and tuple(map(int, CHILD.fullmatch(run["display_title"]).groups()[1:])) in parent_keys)]
    children = {}
    for run in pools["final-review"]:
        match = CHILD.fullmatch(run.get("display_title", ""))
        if match and run.get("event") == "workflow_dispatch":
            children.setdefault(tuple(map(int, match.groups()[1:])), []).append((int(match[1]), run))
    reports, details = [], {}
    for kind, runs in pools.items():
        for run in runs[:20]:
            run_id, attempt = int(run["id"]), int(run["run_attempt"])
            job_states, complete = jobs(reader, run)
            if kind == "implementation" and run.get("event") == "issues" and job_states.get("gate") == "skipped":
                continue
            recorded, artifact_complete = artifacts(reader, run)
            record = {"kind": kind, "run": run_id, "attempt": attempt,
                      "url": f"https://github.com/{repo}/actions/runs/{run_id}/attempts/{attempt}",
                      "status": state(run.get("status"), STATES), "conclusion": state(run.get("conclusion"), RESULTS),
                      "artifacts": recorded, "artifacts_complete": artifact_complete,
                      "findings": [], "jobs_complete": complete, "parent": "unknown"}
            details[(run_id, attempt)] = (record, job_states)
            if kind == "implementation":
                match = ISSUE.fullmatch(run.get("display_title", ""))
                if match and int(match[2]) == attempt:
                    record["issue"] = int(match[1])
                if run.get("status") in {"queued", "in_progress"} and now - instant(run["created_at"]) > timedelta(hours=3):
                    record["findings"].append("stale-implementation")
                if run.get("status") == "completed" and record.get("issue"):
                    issue = reader.get(f"issues/{record['issue']}")
                    if (isinstance(issue, dict) and "pull_request" not in issue
                            and issue.get("user", {}).get("login") == repo.split("/")[0] and any(
                            isinstance(label, dict) and label.get("name") == "implementing" for label in issue.get("labels", []))):
                        record["findings"].append("stale-implementing-label")
                if job_states.get("handoff") == "success" and record.get("issue"):
                    pr = pr_status(reader, repo, record["issue"])
                    if isinstance(pr, dict) and integer(pr.get("number")):
                        record["pr"] = int(pr["number"])
                        record["ci"] = checks(reader, repo, pr.get("head", {}).get("sha"))
                        record["deploy"] = deployment(reader, repo, pr)
            else:
                match = CHILD.fullmatch(run.get("display_title", ""))
                if match:
                    record.update(pr=int(match[1]), parent_run=int(match[2]), parent_attempt=int(match[3]))
                standalone = STANDALONE.fullmatch(run.get("display_title", ""))
                if standalone:
                    record["pr"] = int(standalone[1])
                deduplicated = job_states.get("identify") == "success" and job_states.get("review") == "skipped" and job_states.get("publish") == "skipped"
                if run.get("status") == "completed" and complete and job_states.get("publish") != "success" and not deduplicated:
                    record["findings"].append("final-review-not-delivered")
            if any("recorded-expired" in values for values in recorded.values()):
                record["findings"].append("evidence-expired")
            reports.append(record)
    for run in pools["implementation"][:20]:
        entry = details.get((int(run["id"]), int(run["run_attempt"])))
        if entry is None:
            continue
        record, job_states = entry
        if job_states.get("handoff") != "success" or "pr" not in record:
            continue
        matches = [child for number, child in children.get((record["run"], record["attempt"]), []) if number == record["pr"]]
        record["final_review"] = "unknown"
        if matches:
            record["final_review"] = "observed"
            for child in matches:
                entry = details.get((int(child["id"]), int(child["run_attempt"])))
                if entry:
                    entry[0]["parent"] = "observed"
        elif instant(run.get("updated_at")) and now - instant(run["updated_at"]) > timedelta(minutes=30):
            record["findings"].append("final-review-not-observed")
    bot_keys = {(int(run["id"]), int(run["run_attempt"])) for run in pools["final-review"]
                if run.get("actor", {}).get("login") == "github-actions[bot]"
                or run.get("triggering_actor", {}).get("login") == "github-actions[bot]"}
    reports = [record for record in reports if (record["run"], record["attempt"]) not in bot_keys
               or record["parent"] == "observed"]
    for record in reports:
        record["next_action"] = [ACTIONS[finding] for finding in record["findings"]] or ["Observe; no corrective action inferred."]
    return {"repository": repo, "runs": reports, "notices": sorted(reader.notices),
            "limits": {"days": 90, "pages_per_workflow": 3, "runs_per_workflow": 20,
                       "job_pages_per_run": 3, "artifact_pages_per_run": 1, "requests": 300}, "requests": reader.requests}


def render(report):
    lines = ["## Factory reconciliation (read-only)", "", "Run | State | Findings | CI / deploy | Final review / parent | Artifacts", "--- | --- | --- | --- | --- | ---"]
    for run in report["runs"]:
        artifact_states = sorted({value for values in run["artifacts"].values() for value in values})
        lines.append(f"[{run['run']}.{run['attempt']}]({run['url']}) | {run['status']} / {run['conclusion']} | "
                     + (", ".join(run["findings"]) or "none observed")
                     + f" | {run.get('ci', 'unavailable')} / {run.get('deploy', 'unavailable')}"
                     + f" | {run.get('final_review', 'unknown')} / {run['parent']} | " + ", ".join(artifact_states))
    for finding in sorted({finding for run in report["runs"] for finding in run["findings"]}):
        lines.append(f"{finding}: {ACTIONS[finding]}")
    lines.extend(["", "Coverage: last 90 days; at most 300 run records and 20 detailed runs per workflow; 300 jobs and 100 artifact records per run.",
                  "Artifacts marked absent-unknown may have expired or been deleted. Missing child runs are observations within this scan, not proof of nonexistence."])
    if report["notices"]:
        lines.append("Notices: " + ", ".join(report["notices"]))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    def api(path):
        return json.loads(subprocess.check_output(["gh", "api", "--method", "GET", path], stderr=subprocess.DEVNULL))
    report = reconcile(api, args.repository or "")
    print(json.dumps(report, sort_keys=True) if args.json else render(report), end="\n" if args.json else "")


if __name__ == "__main__":
    main()
