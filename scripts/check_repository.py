"""Offline Git leak guard. Prints locations/rule names, never matched secrets."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

MAX_BYTES = 5 * 1024 * 1024
RULES = {
    "personal home path": rb"/(?:home|Users)/[A-Za-z0-9_.-]+/",
    "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "GitHub token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{40,255})\b",
    "AWS access key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "provider token": rb"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{20,})\b",
    "credential URL": rb"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:[^\s/@]{8,}@",
    "signed URL": rb"(?i)(?:X-Amz-Signature|X-Goog-Signature|[?&]sig)=[a-zA-Z0-9%+/]{16,}",
    "literal credential": rb"""(?im)^\s*["']?(?:[\w-]*(?:password|secret|api_key|access_token|auth_token))["']?\s*[:=]\s*["']([A-Za-z0-9_+/=-]{24,})["']""",
}


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def forbidden(path):
    parts = Path(path).parts
    name = parts[-1].lower()
    if any(
        p
        in {
            ".local",
            ".aws",
            ".ssh",
            "secrets",
            "credentials",
            "backups",
            "node_modules",
            ".venv",
            "__pycache__",
            "playwright-report",
            "test-results",
        }
        for p in parts
    ):
        return True
    if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
        return True
    if name.endswith(".env") or name in {
        "owner.json",
        "role-test-accounts.json",
        "pgadmin.json",
        "database-viewer.json",
        ".pgpass",
        ".npmrc",
        ".netrc",
        ".pypirc",
    }:
        return True
    if "credentials" in name and name.endswith(".json"):
        return True
    if name.endswith(
        (
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".dump",
            ".sqlite",
            ".sqlite3",
            ".db",
            ".log",
            ".sql.gz",
        )
    ):
        return True
    return path.startswith("evaluation/reports/") and name.endswith(
        (".png", ".jpg", ".jpeg", ".mp4", ".wav")
    )


def local_secrets(root):
    """Also catch this deployment's credentials copied under innocent filenames."""
    values = []
    env = root / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and any(
                word in key.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "KEY")
            ):
                values.append(value.strip().strip("\"'"))

    def collect(data):
        if isinstance(data, dict):
            for key, value in data.items():
                if any(
                    word in key.lower() for word in ("password", "token", "secret")
                ) and isinstance(value, str):
                    values.append(value)
                else:
                    collect(value)
        elif isinstance(data, list):
            for value in data:
                collect(value)

    for name in (
        "owner.json",
        "role-test-accounts.json",
        "pgadmin.json",
        "database-viewer.json",
    ):
        credential_file = root / ".local" / name
        if credential_file.is_file():
            collect(json.loads(credential_file.read_text()))
    token = root / ".local/embedding_token"
    if token.is_file():
        values.append(token.read_text().strip())
    return [value.encode() for value in values if len(value) >= 8]


def findings(data, secrets):
    # Exact synthetic URL used by the settings-redaction regression test.
    safe_url = b"postgresql+psycopg://unused:password@127.0.0.1/unused"
    result = [
        name
        for name, pattern in RULES.items()
        if re.search(
            pattern, data.replace(safe_url, b"") if name == "credential URL" else data
        )
    ]
    if any(secret in data for secret in secrets):
        result.append("local deployment credential")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("worktree", "staged", "history", "message"))
    parser.add_argument("message_file", nargs="?")
    parser.add_argument(
        "--push", action="store_true", help="read actual push refs from Git"
    )
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    secrets = local_secrets(root)
    errors = []
    entries = []
    if args.mode == "message":
        if not args.message_file:
            parser.error("message requires a commit message file")
        for rule in findings(Path(args.message_file).read_bytes(), secrets):
            errors.append(("commit message", rule))
    elif args.mode == "worktree":
        paths = git(
            "ls-files", "--cached", "--others", "--exclude-standard", "-z"
        ).split(b"\0")
        for raw in sorted(set(paths) - {b""}):
            path = raw.decode()
            target = root / path
            if target.is_symlink():
                errors.append((path, "symlink requires manual review"))
            elif target.is_file():
                entries.append((path, None, target))
    elif args.mode == "staged":
        for raw in git("ls-files", "--stage", "-z").split(b"\0"):
            if raw:
                metadata, path = raw.split(b"\t", 1)
                mode, oid, stage = metadata.split()
                if mode not in (b"100644", b"100755") or stage != b"0":
                    errors.append((path.decode(), "unsupported index entry"))
                else:
                    entries.append((path.decode(), oid.decode(), None))
    else:
        roots = []
        if args.push:
            for line in sys.stdin:
                fields = line.split()
                if len(fields) != 4 or not re.fullmatch(r"[0-9a-f]{40,64}", fields[1]):
                    raise ValueError("invalid pre-push input")
                if set(fields[1]) != {"0"}:
                    roots.append(fields[1])
        tag_objects = git(
            "for-each-ref", "--format=%(objectname) %(objecttype)", "refs/tags"
        ).splitlines()
        for item in tag_objects:
            oid, kind = item.split()
            if kind == b"tag":
                for rule in findings(git("cat-file", "tag", oid.decode()), secrets):
                    errors.append((f"tag {oid[:12].decode()}", rule))
        for oid in roots:
            kind = git("cat-file", "-t", oid).strip()
            if kind == b"tag":
                for rule in findings(git("cat-file", "tag", oid), secrets):
                    errors.append((f"tag {oid[:12]}", rule))
            if git("cat-file", "-t", oid + "^{}").strip() != b"commit":
                errors.append(
                    (f"object {oid[:12]}", "non-commit push requires manual review")
                )
        if errors:
            commits = []
        else:
            commits = git("rev-list", "--all", *roots).splitlines()
        seen = set()
        for commit in commits:
            message = git("show", "-s", "--format=%B", commit.decode())
            for rule in findings(message, secrets):
                errors.append((f"commit {commit[:12].decode()}", rule))
            for raw in git("ls-tree", "-r", "-z", commit.decode()).split(b"\0"):
                if not raw:
                    continue
                metadata, path = raw.split(b"\t", 1)
                mode, kind, oid = metadata.split()
                identity = (path, oid)
                if identity in seen:
                    continue
                seen.add(identity)
                if mode not in (b"100644", b"100755") or kind != b"blob":
                    errors.append((path.decode(), "unsupported tree entry"))
                else:
                    entries.append((path.decode(), oid.decode(), None))
    checked = set()
    for path, oid, target in entries:
        if forbidden(path):
            errors.append((path, "private/generated path"))
        size = target.stat().st_size if target else int(git("cat-file", "-s", oid))
        if size > MAX_BYTES:
            errors.append((path, "file exceeds 5 MiB; review before publishing"))
            continue
        if oid and oid in checked:
            continue
        data = target.read_bytes() if target else git("cat-file", "blob", oid)
        for rule in findings(data, secrets):
            errors.append((path, rule))
        checked.add(oid)
    for path, rule in sorted(set(errors)):
        print(f"BLOCKED {path!r}: {rule}", file=sys.stderr)
    if errors:
        print(
            "Repository check failed. Remove sensitive content before committing/pushing.",
            file=sys.stderr,
        )
        return 1
    print(f"Repository {args.mode} check passed ({len(entries)} file versions).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError):
        print(
            "Repository check could not complete; commit/push blocked.", file=sys.stderr
        )
        sys.exit(1)
