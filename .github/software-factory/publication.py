"""Pure review publication protocol: markers, rendering and missing-part planning."""
import hashlib
import json
from pathlib import Path
import re


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


COMMENT_BYTES = 60_000




def split(text, budget):
    """Split losslessly into chunks of at most budget UTF-8 bytes, at character boundaries."""
    require(budget > 0, "invalid-comment-header")
    remaining, chunks = text.encode(), []
    while remaining:
        chunk = remaining[:budget].decode("utf-8", errors="ignore")
        require(bool(chunk), "invalid-comment-budget")
        chunks.append(chunk)
        remaining = remaining[len(chunk.encode()):]
    return chunks


FINAL_MARKER = re.compile(r"<!-- tanomu-final-review head=([0-9a-f]{40}) digest=([0-9a-f]{16}) "
                          r"part=([1-9][0-9]*)/([1-9][0-9]*)(?: inline=(none|[0-9a-f]{16}))? -->")
INLINE_MARKER = re.compile(r"<!-- tanomu-final-inline head=([0-9a-f]{40}) digest=([0-9a-f]{16}) -->")


def findings_text(result):
    require(isinstance(result, dict) and all(isinstance(result.get(key), list)
            and all(isinstance(item, str) for item in result[key])
            for key in ("findings", "advisory")), "invalid-review")
    findings = [f"- **Blocking** — {item}" for item in result["findings"]]
    findings += [f"- Advisory — {item}" for item in result["advisory"]]
    return ("### Findings\n\n" + ("\n".join(findings) or "No findings.") + "\n").replace("@", "@" + chr(0x200b))


def compact_summary(result, located):
    """Keep full text only where no inline comment carries that occurrence."""
    remaining = {key: list(result[key]) for key in ("findings", "advisory")}
    for item in located:
        entries = remaining["findings" if item["blocking"] else "advisory"]
        text = f"{item['axis']}: {item['finding']}"
        if text in entries:
            entries.remove(text)
    summary = f"{len(result['findings'])} blocking, {len(result['advisory'])} advisory.\n"
    if located:
        noun = "finding" if len(located) == 1 else "findings"
        summary += f"\n{len(located)} {noun} in inline comments; see those comments for details.\n"
    if any(remaining.values()):
        summary += "\n" + findings_text(remaining).replace("### Findings", "### Other findings", 1)
    elif not located:
        summary += "\nNo findings.\n"
    return summary


def inline_markers(pages):
    return {(match[1], match[2]) for page in pages for item in page
            if item.get("user", {}).get("login") == "github-actions[bot]"
            and item.get("user", {}).get("type") == "Bot"
            and (match := INLINE_MARKER.fullmatch((item.get("body") or "").split("\n", 1)[0]))}


def complete(head, posted, inline):
    sets = {}
    for marker_head, digest, part, total, location in posted:
        if marker_head == head:
            sets.setdefault(digest, []).append((part, total, location))
    for parts in sets.values():
        totals = {total for _, total, _ in parts}
        # A recovered legacy set gains one modern first-part receipt. Its other parts
        # keep their old markers; the receipt declares the inline requirement for the set.
        locations = {location for _, _, location in parts if location is not None}
        total = parts[0][1]
        if (len(totals) != 1 or len(locations) != 1
                or len({part for part, _, _ in parts}) != total
                or max(part for part, _, _ in parts) != total):
            continue
        location = next(iter(locations))
        if location == "none" or (head, location) in inline:
            return True
    return False


def plan(result, reviewed, current, repository, reviews=None):
    report = findings_text(result)
    run, head = reviewed["run"], reviewed["head"]
    spec = (f"Spec: {', '.join(f'#{issue}' for issue in reviewed['issues'])}." if reviewed["issues"] else
            "No issue is linked with Closes/Fixes/Resolves/Refs #N, so only the Standards axis ran.")
    preface = (f"## Final review — head {head[:12]}\n\n"
               f"Merge base {reviewed['base']}. Run: https://github.com/{repository}"
               f"/actions/runs/{run}\n\n{spec} Advisory only: this does not "
               "block merging and nothing was changed.\n\n")
    posted = {tuple(marker[:4]) for marker in current["posted"]}
    files, located = {}, []
    inline = result.get("inline", [])
    require(isinstance(inline, list) and all(
        isinstance(item, dict) and set(item) == {"axis", "blocking", "finding", "path", "line"}
        and isinstance(item["axis"], str) and type(item["blocking"]) is bool
        and isinstance(item["finding"], str) and isinstance(item["path"], str)
        and not item["path"].startswith("/") and ".." not in Path(item["path"]).parts
        and type(item["line"]) is int and item["line"] >= 1 for item in inline), "invalid-inline")
    location = "none"
    if inline:
        # The marker lives in the PR review body, so a rerun with identical findings does not
        # post the same inline comments again. Only the workflow's own reviews count.
        location = hashlib.sha256(json.dumps(inline, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        marker = f"<!-- tanomu-final-inline head={head} digest={location} -->"
        seen = inline_markers(reviews or [])
        comments = []
        for item in inline:
            body = (f"**{item['axis']} · {'blocking' if item['blocking'] else 'advisory'}** — "
                    f"{item['finding']}").replace("@", "@" + chr(0x200b))
            # Oversized findings stay in the losslessly split summary instead.
            if len(body.encode()) <= COMMENT_BYTES:
                located.append(item)
                comments.append({"path": item["path"], "line": item["line"], "side": "RIGHT", "body": body})
        if not comments:
            location = "none"
        if comments and (head, location) not in seen:
            files["inline.json"] = json.dumps({
                "commit_id": head, "event": "COMMENT", "comments": comments,
                "body": f"{marker}\n{len(comments)} inline findings from "
                        f"https://github.com/{repository}/actions/runs/{run}. "
                        "Other findings appear in the summary comment; nothing was changed."}, ensure_ascii=False)
    # Freeze presentation in the review identity so old artifacts retain their original digest.
    compact = reviewed.get("summary_format") == "compact"
    if compact:
        report = compact_summary(result, located)
    # Bind the compact summary to full findings too; equal counts are not equal reports.
    content = json.dumps(result, sort_keys=True, ensure_ascii=False) if compact else report
    # The preface names the run, so each run is a new set while a publisher rerun fills missing parts.
    digest = hashlib.sha256((preface + content).encode()).hexdigest()[:16]
    chunks = split(report, COMMENT_BYTES - len(preface.encode()) - 200)
    legacy = any(len(marker) < 5 or marker[4] is None for marker in current["posted"]
                 if marker[0:2] == [head, digest])
    receipt = any(len(marker) >= 5 and marker[4] is not None for marker in current["posted"]
                  if marker[0:2] == [head, digest])
    for part, chunk in enumerate(chunks, 1):
        if (head, digest, part, len(chunks)) in posted and not (part == 1 and legacy and not receipt):
            continue
        body = (f"<!-- tanomu-final-review head={head} digest={digest} part={part}/{len(chunks)} inline={location} -->\n"
                f"{preface}Part {part}/{len(chunks)}\n\n{chunk}")
        require(len(body.encode()) <= COMMENT_BYTES, "comment-too-large")
        files[f"{part:04d}.md"] = body
    return files
