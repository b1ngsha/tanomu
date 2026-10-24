# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human action                    |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

`agent:implement` is a separate maintainer-only execution signal. It is not a triage role and must never be inferred from `ready-for-agent`. A maintainer adds it only after confirming the issue body, dependencies, and acceptance criteria. The software factory validates that signal before any later implementation workflow can run.

The factory also uses `ready-for-human` after draft-PR delivery: implementation and
round checks/review have completed, while acceptance and the merge decision require
a human. `needs-human` denotes an interrupted or exhausted factory run that needs
diagnosis. Neither label authorizes another implementation run.

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the "Label in our tracker" column to match whatever vocabulary you actually use.
