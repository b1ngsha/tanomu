import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import authorization  # noqa: E402
import control  # noqa: E402


class AuthorizationCompatibilityTest(unittest.TestCase):
    def test_control_reexports_authorization_functions(self):
        for name in ("metadata", "snapshot", "dependencies", "validate_issue", "gate", "revalidate",
                     "claim_identity", "record_claim", "claimed"):
            with self.subTest(name=name):
                self.assertIs(getattr(control, name), getattr(authorization, name))

    def test_isolated_cli_imports_authorization_from_trusted_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            # A candidate module must not replace the trusted authorization implementation.
            (Path(temporary) / "authorization.py").write_text('raise RuntimeError("candidate-import")\n')
            result = subprocess.run([sys.executable, "-I", str(Path(control.__file__).resolve()),
                                     "gate", "0", temporary], cwd=temporary, env={**os.environ},
                                    capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, "", "::error::invalid-issue\n"))


if __name__ == "__main__":
    unittest.main()
