---
status: accepted
---

# Manage stacked pull requests with GitHub gh stack

Tanomu uses GitHub's official `gh stack` extension as the normal interface for stacked pull requests. The existing Admin Console chain is linked as GitHub stack #117. The stack's remote metadata is the source of truth for PR order and base branches; local branches remain the working copy.

The stack manager owns branch ancestry, PR retargeting, cascading rebases, pushes and stack merges. `gh stack sync` and `gh stack rebase` provide the supported recovery path for normal trunk updates, with atomic `--force-with-lease` pushes. Same-repository branches are required; fork branches are outside this workflow.

Agent review remains independent. Its trusted workflow reads the current merge-base-to-head diff and publishes advisory findings, but never retargets, rebases, pushes, merges or closes a PR. A stack operation that changes a PR base or head therefore requires fresh CI and Agent review evidence without granting stack-management permissions to the review workflow.

The repository's `advance-pr-stack` skill is deprecated for normal operations. It remains as a bounded recovery tool for legacy stacks that cannot be imported into GitHub's stack model. Remove it and its regression test after all legacy stacks are migrated and one complete official stack synchronization and merge cycle has been accepted.

GitHub's native stack model is preferred over a third-party service because it keeps repository state, permissions and CI in GitHub, avoids an additional SaaS dependency, and does not expand the Agent review trust boundary. A hosted stack service can be reconsidered if the project later needs team-level stack dashboards or workflow analytics that GitHub does not provide.
