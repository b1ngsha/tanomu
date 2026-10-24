"""Issue authorization, frozen snapshots, and run-bound claim identity."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from common import CREDENTIAL_PATTERN, api, require


def metadata(number):
    require(re.fullmatch(r"[1-9][0-9]*", number), "invalid-issue")
    return {"issue": number, "branch": f"feat/{number}-implement",
            "title": f"feat(repo): implement issue #{number}"}


def snapshot(number, directory):
    record = json.loads((Path(directory) / "input.json").read_text())
    require(all(record.get(key) == value for key, value in {
        **metadata(number), "repository": os.environ["GITHUB_REPOSITORY"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
    }.items()), "stale-input")
    body = (Path(directory) / "issue.md").read_bytes()
    require(hashlib.sha256(body).hexdigest() == record["body_sha256"], "body-changed")
    return record


def dependencies(body):
    # Only an explicit bare same-repository dependency declaration counts.
    declarations = re.findall(
        r"(?<![\w/])blocked by:?[ \t]+(#[1-9][0-9]*(?:[ \t]*,[ \t]*#[1-9][0-9]*)*)\b", body, re.I)
    return list(dict.fromkeys(number for text in declarations
                              for number in re.findall(r"#([1-9][0-9]*)", text)))


def validate_issue(number, claimed=False, captured=None, compare=False):
    spec = metadata(number)
    require(os.environ["GITHUB_REF"] == "refs/heads/main", "wrong-ref")
    repo = os.environ["GITHUB_REPOSITORY"]
    owner = repo.split("/")[0]
    require(os.environ["GITHUB_ACTOR"] == owner, "wrong-actor")
    require(os.environ["GITHUB_TRIGGERING_ACTOR"] == owner, "wrong-triggering-actor")
    issue = api(f"repos/{repo}/issues/{number}")
    require("pull_request" not in issue and issue["state"] == "open", "not-open-issue")
    require(issue["user"]["login"] == owner, "wrong-author")
    labels = {label["name"] for label in issue["labels"]}
    authorization = "implementing" if claimed else "agent:implement"
    forbidden = {"needs-human", "ready-for-human", "agent:implement" if claimed else "implementing"}
    require({"ready-for-agent", authorization} <= labels, "missing-authorization")
    require(not forbidden & labels, "already-claimed")
    events = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues/{number}/events?per_page=100"
    ]))
    authorizations = [event for page in events for event in page
                      if event.get("event") in ("labeled", "unlabeled")
                      and event.get("label", {}).get("name") == authorization]
    require(bool(authorizations) and authorizations[-1]["event"] == "labeled"
            and authorizations[-1]["actor"]["login"] == ("github-actions[bot]" if claimed else owner),
            "wrong-label-actor")
    body = issue.get("body") or ""
    if captured is not None and compare:
        require(hashlib.sha256(body.encode()).hexdigest() == captured["body_sha256"]
                and issue.get("title", "") == captured["issue_title"], "body-changed")
        if not claimed:
            require(authorizations[-1]["id"] == captured["authorization_id"], "stale-authorization")
    blockers = dependencies(body) if captured is None else captured["blocked_by"]
    if captured is None or compare:
        require(not issue.get("issue_dependencies_summary", {}).get("blocked_by", 0),
                "open-dependency")
    for dependency in blockers:
        blocker = api(f"repos/{repo}/issues/{dependency}")
        require(blocker["state"] == "closed" and blocker.get("state_reason") == "completed",
                "open-dependency")
    refs = api(f"repos/{repo}/git/matching-refs/heads/{spec['branch']}")
    require(not any(ref["ref"] == f"refs/heads/{spec['branch']}" for ref in refs), "branch-exists")
    pulls = api(f"repos/{repo}/pulls?state=all&head={owner}:{spec['branch']}")
    require(not pulls, "pr-exists")
    return issue, authorizations[-1], blockers


def gate(number, directory):
    issue, event, blockers = validate_issue(number)
    body = issue.get("body") or ""
    require(not CREDENTIAL_PATTERN.search((body + issue.get("title", "")).encode()),
            "credential-pattern-in-artifact")
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "issue.md").write_text(body)
    (output / "input.json").write_text(json.dumps({
        **metadata(number), "repository": os.environ["GITHUB_REPOSITORY"],
        "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "issue_title": issue.get("title", ""), "blocked_by": blockers,
        "authorization_id": event["id"],
    }))


def revalidate(number, directory):
    validate_issue(number, captured=snapshot(number, directory), compare=True)


def claim_identity(number, event):
    require(type(event.get("id")) is int and event["id"] > 0, "invalid-claim-event")
    return {"issue": number, "repository": os.environ["GITHUB_REPOSITORY"],
            "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "event_id": event["id"]}


def record_claim(number, directory, filename):
    captured = snapshot(number, directory)
    _, event, _ = validate_issue(number, claimed=True, captured=captured, compare=True)
    Path(filename).write_text(json.dumps({**claim_identity(number, event), "snapshot": captured}))


def claimed(number, directory, filename):
    captured = snapshot(number, directory)
    _, event, _ = validate_issue(number, claimed=True, captured=captured)
    record = json.loads(Path(filename).read_text())
    require(record == {**claim_identity(number, event), "snapshot": captured}, "stale-claim")
