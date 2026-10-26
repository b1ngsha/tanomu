"""Small shared primitives for trusted factory controllers."""
import json
import re
import subprocess


# Credential-shaped tokens; the lookbehind keeps kebab-case text such as "task-..." from matching.
CREDENTIAL_PATTERN = re.compile(
    rb"(?<![A-Za-z0-9_-])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
    rb"|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path]))
