"""Exercise leak guards in disposable repositories, without touching project Git."""

import importlib.util
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("check_repository.py")
spec = importlib.util.spec_from_file_location("guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class RepositoryGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "Guard Test")
        self.git("config", "user.email", "guard@example.invalid")
        self.git("config", "core.hooksPath", "/dev/null")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True
        )

    def scan(self, mode, *args, input=None):
        return subprocess.run(
            ["python3", str(SCRIPT), mode, *args],
            cwd=self.root,
            capture_output=True,
            input=input,
        )

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)

    def test_clean_and_empty_history(self):
        self.assertEqual(self.scan("history").returncode, 0)
        self.write("app.py", "print('hello')\n")
        self.git("add", ".")
        self.assertEqual(self.scan("staged").returncode, 0)

    def test_force_added_environment_is_blocked(self):
        self.write(".gitignore", ".env.production\n")
        self.write(".env.production", "EXAMPLE=example\n")
        self.git("add", "-f", ".env.production")
        self.assertNotEqual(self.scan("staged").returncode, 0)

    def test_index_content_wins_over_clean_worktree(self):
        token = "gh" + "p_" + "A" * 36
        self.write("app.py", token)
        self.git("add", ".")
        self.write("app.py", "clean")
        result = self.scan("staged")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(token.encode(), result.stderr)

    def test_deleted_secret_is_found_in_history(self):
        self.write("old.txt", "hf" + "_" + "A" * 32)
        self.git("add", ".")
        self.git("commit", "-qm", "test: fixture")
        self.git("rm", "old.txt")
        self.git("commit", "-qm", "test: delete fixture")
        self.assertNotEqual(self.scan("history").returncode, 0)

    def test_local_secret_copied_to_innocent_file(self):
        secret = "deployment-" + "z" * 28
        self.write(".env", "APP_DB_PASSWORD=" + secret)
        self.write("notes.md", secret)
        self.git("add", "notes.md")
        self.assertNotEqual(self.scan("staged").returncode, 0)

    def test_large_file_and_symlink(self):
        self.write("large.txt", "x" * (guard.MAX_BYTES + 1))
        self.git("add", ".")
        self.assertNotEqual(self.scan("staged").returncode, 0)
        self.git("rm", "--cached", "large.txt")
        (self.root / "link").symlink_to("/etc/passwd")
        self.git("add", "link")
        self.assertNotEqual(self.scan("staged").returncode, 0)

    def test_commit_message(self):
        self.write("message", "token=" + "gh" + "p_" + "A" * 36)
        self.assertNotEqual(self.scan("message", "message").returncode, 0)

    def test_actual_commit_hook_blocks_secret(self):
        (self.root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.root / "scripts/check_repository.py")
        self.git("config", "core.hooksPath", str(SCRIPT.parent.parent / ".githooks"))
        self.write("notes.md", "gh" + "p_" + "A" * 36)
        self.git("add", "notes.md")
        result = subprocess.run(
            ["git", "commit", "-m", "test: fixture"], cwd=self.root, capture_output=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"GitHub token", result.stderr)

    def test_push_checks_unreferenced_commit(self):
        self.write("notes.md", "hf" + "_" + "A" * 32)
        self.git("add", ".")
        self.git("commit", "-qm", "test: fixture")
        oid = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.git("update-ref", "-d", "refs/heads/main")
        push_line = f"{oid} {oid} refs/heads/example {'0' * 40}\n".encode()
        self.assertNotEqual(
            self.scan("history", "--push", input=push_line).returncode, 0
        )

    def test_annotated_tag_message(self):
        self.write("notes.md", "safe")
        self.git("add", ".")
        self.git("commit", "-qm", "test: fixture")
        self.git("tag", "-a", "example", "-m", "gh" + "p_" + "A" * 36)
        self.assertNotEqual(self.scan("history").returncode, 0)

    def test_synthetic_exception_does_not_hide_other_urls(self):
        safe = b"postgresql+psycopg://unused:password@127.0.0.1/unused"
        self.assertEqual(guard.findings(safe, []), [])
        unsafe = b"postgresql://" + b"admin:real-credential-value@db/app"
        self.assertIn("credential URL", guard.findings(safe + unsafe, []))

    def test_private_paths_and_scanner_rules(self):
        for path in (".local/owner.json", "backup.dump", "evaluation/reports/a.png"):
            self.assertTrue(guard.forbidden(path))
        examples = [
            b"/" + b"home/example/private/file",
            b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
            b"AK" + b"IA" + b"A" * 16,
            b"X-Amz-" + b"Signature=" + b"a" * 64,
            b'api_key="' + b"a" * 32 + b'"',
        ]
        for example in examples:
            self.assertTrue(guard.findings(example, []))


if __name__ == "__main__":
    unittest.main()
