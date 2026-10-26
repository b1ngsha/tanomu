---
name: advance-pr-stack
description: Advance a linear PR stack after its parent merges.
disable-model-invocation: true
argument-hint: <direct-child-pr> [--dry-run|--apply]
---

# Advance a PR stack

```sh
python3 -I .claude/skills/advance-pr-stack/scripts/advance.py <direct-child-pr> --dry-run
```

Run from the repository root for the direct child of a merged `main` PR. Default dry-run reads Git/GitHub without fetching or writing. Local branches must match GitHub heads, contain all commits and be checked out in no worktree; use an unrelated current branch with clean tracked files/index. Untracked files are preserved.

With explicit user authorization, repeat with `--apply`. This fetches `main` and heads, restores a deleted parent and reopens the child only when its timeline proves `base_ref_deleted` caused closure, then retargets the child to `main`. Descendants replay parent-first. Each PR's binary full-index diff must stay identical and within CI's 600-line limit. Rewritten heads use one atomic push with exact leases and no followed tags.

Only matching github.com origins and same-repository linear chains are supported. Ambiguity, forks, conflicts, changed diffs, oversized PRs and concurrent changes stop the run. The helper never changes authentication, deletes branches, merges/closes PRs or dispatches review.

On failure, keep the printed journal and replay worktree. Inspect completed/pending writes and GitHub before continuing: a pending write may have succeeded despite a network error. Obtain explicit confirmation before rollback or destructive restoration; the helper never performs either. Test with `python3 -I .claude/skills/advance-pr-stack/scripts/test_advance.py`.
