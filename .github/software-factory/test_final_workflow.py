import json
import re
import subprocess
import unittest

import test_control as base
from test_control import CONTROL, REPO, SECRET, control

HEAD, BASE = "a" * 40, "b" * 40
PULL = {"state": "open", "body": "", "user": {"type": "User"}, "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        "base": {"ref": "main", "sha": "d" * 40, "repo": {"full_name": REPO}}}
# Serves the PR and its comments, and saves each posted body in order.
GH = ('case "$2" in repos/*/pulls/*) cat "$CALLS/../pull.json";; --paginate) cat "$CALLS/../comments.json";;\n'
      'comment) mkdir -p "$CALLS/../bodies"; cp "$5" "$CALLS/../bodies/$(printf %03d $(ls "$CALLS" | wc -l))";; esac')


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class FinalRunnerStepTest(unittest.TestCase):
    """Runs the real final review step scripts against stub `opencode`, `gh` and `timeout`."""

    jobs = {"identify": ("final-review.yml", "identify"),
            "review": ("final-review.yml", "review"), "publish": ("final-review.yml", "publish"),
            "handoff": ("software-factory-implement.yml", "handoff")}
    run_step, calls, uploaded = base.RunnerStepTest.run_step, base.RunnerStepTest.calls, base.RunnerStepTest.uploaded
    stub_events, reply = base.RunnerStepTest.stub_events, base.RunnerStepTest.reply

    def review(self, opencode, spec="true"):
        env = {"HEAD": HEAD, "BASE": BASE, "SPEC": spec}
        files = {"temp/final-input/identity.json": '{"run":"42"}',
                 "candidate/.factory-input/identity.json": '{"run":"forged"}'}
        return self.run_step("review", opencode, env=env, files=files, setup=lambda directory: env.update(
            REVIEW_OUTPUT=str(directory / "temp/final-review/review.json")))

    def temp(self, name):
        return self.directory / "temp" / name

    def test_reviews_each_axis_in_a_fresh_session_and_ignores_the_verdict(self):
        reply = self.reply({"findings": [{"blocking": True, "finding": "src/a.ts: breaks AGENTS.md"}]})
        for spec, axes in (("true", ["standards", "spec"]), ("false", ["standards"])):
            with self.subTest(spec=spec):
                result, summary = self.review(reply, spec)
                self.assertEqual(result.returncode, 0, result.stderr)
                sessions = self.calls("opencode")
                self.assertEqual(len(sessions), len(axes))
                self.assertEqual(summary.count("### OpenCode run"), len(axes))
                for axis, session in zip(axes, sessions):
                    self.assertIn("--standalone", session)
                    self.assertEqual(session[-1], control.prompt(f"final-{axis}", BASE, HEAD).rstrip("\n"))
                    self.assertIn("final.patch", session[-1])
                review = json.loads(self.temp("final-review/review.json").read_text())
                self.assertEqual((review["verdict"], len(review["findings"])), ("request_changes", len(axes)))
                self.assertTrue(self.temp("final-review/review.md").is_file())
                self.assertEqual(json.loads(self.temp("final-review/identity.json").read_text()), {"run": "42"})

    def test_timeout_and_failure_exits_are_preserved_without_leaking(self):
        for opencode, status in ((f"echo {SECRET} >&2\nexec sleep 20", 124), ("exit 3", 3)):
            with self.subTest(status=status):
                result, _ = self.review(opencode)
                self.assertEqual(result.returncode, status)
                self.assertIn(f"::error::opencode-exit-{status}", result.stdout)
                self.assertNotIn(SECRET, result.stdout + result.stderr)
                # The failed axis stops the run before the next one spends its budget.
                self.assertEqual(len(self.calls("opencode")), 1)

    def test_sessions_are_always_recorded_and_scanned(self):
        for spec, axes in (("true", ["standards", "spec"]), ("false", ["standards"])):
            with self.subTest(spec=spec):
                files = {"temp/final-standards-summary.txt": "opencode-summary {}\n", "temp/session/leak.txt": SECRET}
                result, _ = self.run_step("review", select="control.py transcript", env={"SPEC": spec}, files=files)
                self.assertEqual(result.returncode, 0, result.stderr)
                # Only the scanned transcripts and summary, never the planted leak.
                self.assertEqual(sorted(self.uploaded("review")), sorted(
                    [f"final-{axis}.md" for axis in axes] + ["final-standards-summary.txt"]))
                leak = json.dumps({"type": "text", "part": {"text": SECRET}}) + "\n"
                result, _ = self.run_step("review", select="control.py transcript", env={"SPEC": spec},
                                          files={"temp/final-standards.jsonl": leak})
                self.assertEqual(result.returncode, 1)
                self.assertIn("::error::credential-in-artifact", result.stderr)
                self.assertNotIn(SECRET, result.stdout + result.stderr)

    def stage(self, plant=lambda candidate: None):
        env = {}

        def setup(directory):
            candidate = directory / "candidate"
            git(candidate, "init", "-q", "-b", "main")
            (candidate / "a.txt").write_text("base\n")
            git(candidate, "add", ".")
            git(candidate, "commit", "-qm", "base")
            env["BASE"] = git(candidate, "rev-parse", "HEAD")
            (candidate / "a.txt").write_text("head\n")
            (candidate / "key").symlink_to(directory / "auth.json")
            (candidate / "docs").mkdir()
            (candidate / "docs/up").symlink_to("../..")
            plant(candidate)
            git(candidate, "add", "-A")
            git(candidate, "commit", "-qm", "head")
            env["HEAD"] = git(candidate, "rev-parse", "HEAD")
        files = {"temp/final-input/identity.json": "{}", "temp/final-input/issue-6.md": "# Issue #6\n"}
        # setup fills env before run_step reads it.
        result, _ = self.run_step("review", select="control.py pr-diff", files=files, setup=setup, env=env)
        return result, self.directory / "candidate"

    def test_stage_writes_diff_and_issues_as_data_and_drops_symlinks(self):
        result, candidate = self.stage()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(path.name for path in (candidate / ".factory-input").iterdir()),
                         ["final.patch", "identity.json", "issue-6.md"])
        patch = (candidate / ".factory-input/final.patch").read_text()
        self.assertIn("+head", patch)
        self.assertIn("new file mode 120000", patch)
        self.assertEqual([path for path in candidate.rglob("*") if path.is_symlink()], [])
        self.assertEqual((candidate / "a.txt").read_text(), "head\n")

    def test_stage_rejects_a_planted_factory_input(self):
        def directory(candidate):
            (candidate / ".factory-input").mkdir()
            (candidate / ".factory-input/final.patch").write_text("forged\n")
        for plant in (directory, lambda candidate: (candidate / ".factory-input").symlink_to("../temp")):
            with self.subTest(plant=plant):
                result, candidate = self.stage(plant)
                self.assertEqual(result.returncode, 1)
                self.assertIn("::error::factory-input-exists", result.stdout + result.stderr)
                self.assertFalse((self.directory / "temp/final.patch").exists())
                self.assertFalse((self.directory / "temp/identity.json").exists())

    def publish(self, head=HEAD, comments=(), report="Looks fine. @maintainer\n"):
        files = {"pull.json": json.dumps({**PULL, "head": {**PULL["head"], "sha": head}}),
                 "comments.json": json.dumps([list(comments)]),
                 "temp/input/identity.json": json.dumps({"pr": 17, "head": HEAD, "base": BASE, "issues": [], "run": "42"}),
                 "temp/review/review.json": json.dumps({"verdict": "approve", "findings": [], "advisory": []}),
                 "temp/review/review.md": report}
        result, _ = self.run_step("publish", gh=GH, select="control.py final-head", files=files, env={
            "PR": "17", "GITHUB_REF": "refs/heads/main", "GH_REPO": REPO, "FACTORY_AUTH_FILE": ""})
        bodies = self.directory / "bodies"
        return result, [path.read_text() for path in sorted(bodies.iterdir())] if bodies.exists() else []

    def test_publisher_posts_every_part_in_order(self):
        report = base.mixed_text(80_000)
        result, bodies = self.publish(report=report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(len(bodies), 1)
        for part, body in enumerate(bodies, 1):
            self.assertRegex(body.split("\n", 1)[0], rf"<!-- tanomu-final-review head={HEAD} "
                                                     rf"digest=[0-9a-f]{{16}} part={part}/{len(bodies)} -->")
            self.assertLessEqual(len(body.encode()), 60_000)
        self.assertTrue(all(call[:3] == ["pr", "comment", "17"] for call in self.calls("gh")[2:]))
        self.assertIn(report.replace("@", "@​")[-500:], "".join(bodies))
        # A rerun after a partial post fills in only the missing parts.
        posted = [{"body": bodies[0], "user": {"login": "github-actions[bot]", "type": "Bot"}}]
        result, rest = self.publish(comments=posted, report=report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(rest, bodies[1:])

    def test_publisher_skips_a_moved_head(self):
        result, bodies = self.publish(head="c" * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::notice::final-review-stale", result.stdout)
        self.assertEqual(bodies, [])
        self.assertFalse(any(call[:2] == ["pr", "comment"] for call in self.calls("gh")))

    def test_manual_resume_step_emits_false_without_running_the_model(self):
        result, _ = self.run_step("identify", select="control.py final-resume", env={
            "PR": "17", "EVENT": "workflow_dispatch", "GITHUB_REF": "refs/heads/main"},
            files={"temp/final-input/identity.json": '{"run":"123"}'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / "output").read_text(), "resumed=false\n")
        self.assertEqual(self.calls("opencode"), [])

    def test_handoff_starts_the_review_only_for_a_pr_number(self):
        for pr, started in (("17", True), ("", False), ("0", False), ("17\nx", False), ("1;id", False)):
            with self.subTest(pr=pr):
                result, _ = self.run_step("handoff", select="gh workflow run", env={"PR": pr})
                self.assertEqual(result.returncode, 0 if started else 1)
                self.assertEqual(self.calls("gh"), [["workflow", "run", "final-review.yml", "--ref", "main",
                                                     "-f", f"pr={pr}"]] if started else [])


class FinalWorkflowContractTest(unittest.TestCase):
    """The final review reads an untrusted head, so pin who runs what with which token."""

    def setUp(self):
        self.workflow = base.WorkflowContractTest.load("final-review.yml")
        self.jobs = self.workflow["jobs"]

    def test_triggers_run_trusted_main_only(self):
        triggers = self.workflow[True]  # YAML 1.1 reads `on` as true.
        self.assertEqual(set(triggers), {"pull_request_target", "workflow_dispatch"})
        self.assertEqual(triggers["pull_request_target"]["types"], ["opened", "reopened", "ready_for_review"])
        self.assertEqual(triggers["pull_request_target"]["branches"], ["main"])
        self.assertEqual(self.workflow["permissions"], {})
        self.assertFalse(self.workflow["concurrency"]["cancel-in-progress"])
        gate = self.jobs["identify"]["if"]
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", gate)
        self.assertIn("github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'", gate)
        for name, job in self.jobs.items():
            for step in job["steps"]:
                if "actions/checkout" in step.get("uses", ""):
                    with self.subTest(job=name, path=step["with"].get("path")):
                        self.assertIs(step["with"]["persist-credentials"], False)
                        candidate = step["with"].get("path") == "candidate"
                        self.assertEqual(step["with"]["ref"], "${{ needs.identify.outputs.head }}" if candidate
                                         else "${{ github.sha }}")
                        self.assertEqual(candidate, name == "review" and step["with"].get("fetch-depth") == 0)

    def test_permissions_and_secrets_are_split(self):
        self.assertEqual({name: job["permissions"] for name, job in self.jobs.items()}, {
            "identify": {"actions": "read", "contents": "read", "issues": "read", "pull-requests": "read"},
            "review": {"contents": "read"},
            "publish": {"contents": "read", "issues": "write", "pull-requests": "write"}})
        text = {name: json.dumps(job) for name, job in self.jobs.items()}
        self.assertEqual([name for name in text if "secrets." in text[name]], ["review"])
        self.assertNotIn("GH_TOKEN", text["review"])
        self.assertNotIn("github.token", text["review"])
        self.assertNotIn("opencode", text["publish"].lower())

    def test_candidate_is_data_only(self):
        review = self.jobs["review"]
        # --standalone alone still loads and executes workspace plugins and config.
        self.assertEqual(review["env"], {"OPENCODE_CONFIG_PROJECT_DISABLE": "1", "OPENCODE_DISABLE_CLAUDE_CODE": "1"})
        steps = review["steps"]
        uses = {re.sub(r"@.*", "", step["uses"]) for step in steps if "uses" in step}
        self.assertEqual(uses, {"actions/checkout", "actions/download-artifact", "actions/upload-artifact"})
        for step in steps:
            run, path = step.get("run", ""), step.get("with", {}).get("path", "")
            with self.subTest(step=step.get("name", step.get("uses"))):
                self.assertNotRegex(run, r"(?<![\w.])(pnpm|npx|node|make|git|bash|sh|source)\b|(?<![\w.])\./\w")
                self.assertEqual(re.findall(r"python3 (?!-I (\.\./)?trusted/)", run), [])
                if "download-artifact" in step.get("uses", ""):
                    self.assertFalse(path.startswith("candidate"), path)
        stage = next(step["run"] for step in steps if "control.py pr-diff" in step.get("run", ""))
        order = ["[ -e .factory-input ] || [ -L .factory-input ]", "control.py pr-diff", "-type l -exec rm",
                 "cp -- "]
        self.assertEqual(sorted(order, key=stage.index), order)
        names = [step.get("with", {}).get("name") or step.get("name") for step in steps]
        self.assertLess(names.index("final-input"), names.index("Stage PR diff and issues as data"))
        self.assertLess(names.index("Stage PR diff and issues as data"), names.index("Install pinned runner"))

    def test_runner_model_and_actions_are_pinned(self):
        for path in (CONTROL.parents[2] / ".github/workflows").glob("*.yml"):
            if path.name == "ci.yml":
                continue
            with self.subTest(workflow=path.name):
                for action in re.findall(r"uses: (\S+)", path.read_text()):
                    self.assertRegex(action, r"^[\w-]+/[\w-]+@[0-9a-f]{40}$|^\./")
        run = json.dumps(self.jobs["review"])
        self.assertIn("@opencode/cli@2.1.0 --no-audit --no-fund && opencode --version | grep -Fx 'opencode v2.1.0'",
                      run)
        model = next(step for step in self.jobs["review"]["steps"] if "opencode run" in step.get("run", ""))
        self.assertEqual(model["env"]["MODEL"], control.MODEL)
        self.assertEqual(re.findall(r"timeout --kill-after=15 (\d+) opencode run", model["run"]), ["600"])
        self.assertIn('configure \\"$RUNNER_TEMP/model\\" review', run)

    def test_artifacts_are_explicit_and_expire_after_three_days(self):
        all_uploads = [step for job in self.jobs.values() for step in job["steps"]
                       if "upload-artifact" in step.get("uses", "")]
        uploads = {step["with"]["name"]: step for step in all_uploads}
        self.assertEqual(set(uploads), {"final-input", "final-review", "session-final-review"})
        for step in all_uploads:
            name = step["with"]["name"]
            with self.subTest(artifact=name):
                self.assertEqual(step["with"]["retention-days"], 3)
                self.assertNotIn("*", step["with"]["path"])
        self.assertEqual(uploads["session-final-review"]["if"], "always() && steps.session.outcome == 'success'")
        record = next(step for step in self.jobs["review"]["steps"] if step.get("id") == "session")
        self.assertEqual((record["if"], record["continue-on-error"]), ("always()", True))

    def test_recovery_is_selected_before_upload_and_bypasses_the_model(self):
        identify = self.jobs["identify"]
        self.assertEqual(identify["outputs"]["resumed"], "${{ steps.resume.outputs.resumed }}")
        steps = identify["steps"]
        resume = next(step for step in steps if step.get("id") == "resume")
        self.assertEqual(resume["if"], "steps.identify.outputs.skip != 'true'")
        self.assertIn('final-resume "$PR" "$EVENT"', resume["run"])
        self.assertIn('"$RUNNER_TEMP/final-input" "$RUNNER_TEMP/final-review" >> "$GITHUB_OUTPUT"', resume["run"])
        uploads = [step for step in steps if "upload-artifact" in step.get("uses", "")]
        self.assertTrue(all(steps.index(resume) < steps.index(step) for step in uploads))
        report = next(step for step in uploads if step["with"]["name"] == "final-review")
        self.assertEqual(report["if"], "steps.resume.outputs.resumed == 'true'")
        fresh = next(step for step in self.jobs["review"]["steps"]
                     if step.get("with", {}).get("name") == "final-review")
        self.assertEqual(report["with"], fresh["with"])
        self.assertIn("/identity.json", fresh["with"]["path"])
        # Evaluate the actual job gates for fresh, resumed, failed, skipped and cancelled runs.
        for resumed, skip, identified, reviewed, cancelled, expected in (
                (False, False, "success", "success", False, (True, True)),
                (True, False, "success", "skipped", False, (False, True)),
                (False, False, "success", "failure", False, (True, False)),
                (True, False, "failure", "skipped", False, (False, False)),
                (True, True, "success", "skipped", False, (False, False)),
                (True, False, "success", "skipped", True, (False, False))):
            with self.subTest(resumed=resumed, skip=skip, identified=identified, reviewed=reviewed,
                              cancelled=cancelled):
                values = {"needs.identify.outputs.resumed": str(resumed).lower(),
                          "needs.identify.outputs.skip": str(skip).lower(), "needs.identify.result": identified,
                          "needs.review.result": reviewed}
                gates = []
                for job in ("review", "publish"):
                    expression = self.jobs[job]["if"].replace("always()", "True").replace("cancelled()", str(cancelled))
                    for key, value in values.items():
                        expression = expression.replace(key, repr(value))
                    expression = re.sub(r"!(?!=)", "not ", expression)
                    gates.append(eval(expression.replace("&&", "and").replace("||", "or"), {"__builtins__": {}}))
                self.assertEqual(tuple(gates), expected)

    def test_publisher_rechecks_the_head_before_posting(self):
        run = next(step["run"] for step in self.jobs["publish"]["steps"] if "gh pr comment" in step.get("run", ""))
        order = ["control.py final-head", "control.py final-comments", "gh pr comment"]
        self.assertEqual(sorted(order, key=run.index), order)
        self.assertIn("--body-file", run)
        self.assertEqual(set(self.jobs["publish"]["needs"]), {"identify", "review"})

    def test_handoff_dispatches_the_review_without_risking_the_handoff(self):
        handoff = base.WorkflowContractTest.load("software-factory-implement.yml")["jobs"]["handoff"]
        self.assertEqual(handoff["permissions"]["actions"], "write")
        steps = handoff["steps"]
        create = next(index for index, step in enumerate(steps) if "gh pr create" in step.get("run", ""))
        self.assertEqual(steps[create]["id"], "pr")
        dispatch = steps[create + 1]
        self.assertTrue(dispatch["continue-on-error"])
        self.assertEqual(dispatch["env"]["PR"], "${{ steps.pr.outputs.pr }}")
        self.assertIn('gh workflow run final-review.yml --ref main -f pr="$PR"', dispatch["run"])
        self.assertEqual(len(steps), create + 2)
