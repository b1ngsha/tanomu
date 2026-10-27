# Stacked pull requests

Tanomu uses GitHub's official `gh stack` extension for stacked pull requests. The GitHub stack is the source of truth for PR order and base branches; local Git branches are the working copy. Agent review is a separate read-only workflow that reviews the current base-to-head diff and never manages the stack.

## Before starting a stack

Install and authenticate the official extension once:

```sh
gh extension install github/gh-stack
gh auth status
```

Use same-repository branches. Fork branches are not part of the supported stack workflow. Keep each layer independently reviewable and within the repository's 600 changed-line limit.

## Create and publish a stack

Start from the repository's trunk and create layers from bottom to top:

```sh
gh stack init <first-branch>
# make and commit the first layer
gh stack add <second-branch>
# make and commit the second layer
gh stack submit
```

`gh stack submit --auto` avoids the interactive editor. Review the generated PR titles and descriptions before publishing a new stack. Existing branches can be adopted with `gh stack init branch-1 branch-2 branch-3` when the branches already form a linear local chain.

To link existing PRs without adopting local stack tracking, use the bottom-to-top order explicitly:

```sh
gh stack link <bottom-pr-or-branch> <next-pr-or-branch> <top-pr-or-branch>
```

The link operation creates or updates GitHub stack metadata. It does not merge PRs and should be followed by a read-only status check.

## Daily synchronization

Use the official commands for stack state:

```sh
gh stack view --short
gh stack sync
gh stack rebase
gh stack push
```

`gh stack sync` fetches GitHub, reconciles local stack metadata, rebases layers after trunk changes, pushes with `--force-with-lease` atomically, and synchronizes the remote stack. A conflict restores the original branches; resolve it with `gh stack rebase`, then continue and push after reviewing the diff.

After any rebase or push, check every layer's incremental diff and CI status. A changed base or head is expected to invalidate the previous Agent review; the independent Agent review workflow owns that status and should not be granted stack-management permissions.

## Merge

Use the stack merge operation for a stack:

```sh
gh stack merge
```

Merge proceeds from the bottom layer upward and respects the stack's review and check requirements. Do not use `gh pr merge` to bypass the stack relationship. Inspect the GitHub stack and each PR after the merge; GitHub may cascade the rebase and update dependent layers.

## Existing stack migration

The existing Admin Console chain was linked as GitHub stack #117 in this order:

```text
main
  -> #103 feat/4-admin-console-tests
  -> #104 feat/4-admin-binding
  -> #106 feat/4-admin-structure
  -> #107 feat/4-admin-test-layout
  -> #109 refactor/4-provider-create-update
  -> #111 refactor/4-admin-vertical-whitespace
  -> #113 ci/unused-export-check
```

Adopt it in a clean checkout with `gh stack checkout 117`, then run `gh stack view --short`. Do not run adoption from a worktree containing unrelated uncommitted changes. Before the first merge, confirm that every PR still has the expected base and head, all required CI checks are green, and the incremental diff remains unchanged.

## Agent review boundary

Stack management and Agent review are independent:

- `gh stack` owns branch ancestry, PR base branches, rebases, pushes, and stack merges.
- `agent-review.yml` and `agent-review-status.yml` own advisory review execution and publication status.
- Agent review reads the actual merge-base-to-head diff, binds freshness to the current PR revision, and never retargets, rebases, pushes, merges, or closes a PR.
- A stack operation can change a PR base or head without changing its feature intent; CI and Agent review still need fresh evidence for the new revision.
