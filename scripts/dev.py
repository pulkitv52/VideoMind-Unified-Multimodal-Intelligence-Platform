"""Local lifecycle commands; credentials are generated once and kept private."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def setup():
    env = ROOT / ".env"
    if not env.exists():
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            for key in (
                "POSTGRES_PASSWORD",
                "APP_DB_PASSWORD",
                "REDIS_PASSWORD",
                "MINIO_ROOT_PASSWORD",
                "MINIO_APP_PASSWORD",
            ):
                output.write(f"{key}={secrets.token_hex(32)}\n")
    (ROOT / ".local").mkdir(mode=0o700, exist_ok=True)
    token = ROOT / ".local/embedding_token"
    if not token.exists():
        fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_hex(32))
    (ROOT / ".local/imports").mkdir(mode=0o755, exist_ok=True)


def compose(*args):
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / ".env"),
            "-f",
            str(ROOT / "infra/compose/compose.yaml"),
            *args,
        ],
        cwd=ROOT,
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("setup", "up", "down", "status", "verify", "bootstrap")
    )
    args = parser.parse_args()
    setup()
    if args.action == "up":
        from prepare_asr import prepare

        prepare()
        from prepare_embedding import prepare as prepare_embeddings

        prepare_embeddings()
        compose("up", "--build", "--wait", "--wait-timeout", "180")
        compose("run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "bootstrap")
        print(
            "Open http://localhost:8080; sign-in credentials are in .local/owner.json"
        )
    elif args.action == "bootstrap":
        compose("run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "bootstrap")
    elif args.action == "verify":
        compose("build", "verify")
        compose("run", "--rm", "verify")
    elif args.action == "down":
        compose("down")  # Preserve named volumes.
    elif args.action == "status":
        compose("ps")
    else:
        print("Local configuration ready; existing credentials were preserved")


if __name__ == "__main__":
    main()
