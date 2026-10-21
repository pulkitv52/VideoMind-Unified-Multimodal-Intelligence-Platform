"""Operator-only stdin bridge into the existing private CPU service; no HTTP route."""

import hashlib
import json
import subprocess
import select
from pathlib import Path

BRIDGE = """
import json,sys
from videomind.embeddings.client import Client
from videomind.embeddings.indexer import heavy
from videomind.infrastructure.database import database
from videomind.config import Settings
c=Client();profile=c.profile();engine=database(Settings().database_url.get_secret_value())
for line in sys.stdin:
 try:
  value=json.loads(line)
  if value.pop('profile')!=profile.fingerprint:raise ValueError('profile')
  with heavy(engine):result=c.encode(profile.fingerprint,configuration=profile.model_dump(mode='json'),**value)
  print(json.dumps(result),flush=True)
 except Exception:print(json.dumps({'error':'ENCODE_FAILED'}),flush=True)
engine.dispose()
"""


class Encoder:
    def __init__(self, root, profile, response_timeout=180):
        self.root = root
        self.response_timeout = response_timeout
        self.profile = profile
        self.process = None
        self.cache = root / ".local/evaluation-vectors"
        self.cache.mkdir(mode=0o700, exist_ok=True)

    def encode(self, kind, content, query=False):
        payload = {
            "profile": self.profile,
            "kind": kind,
            "content": content,
            "query": query,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        path = self.cache / (digest + ".json")
        if path.exists():
            result = json.loads(path.read_text())
        else:
            if self.process is None:
                self.process = subprocess.Popen(
                    [
                        "docker",
                        "compose",
                        "--env-file",
                        str(self.root / ".env"),
                        "-f",
                        str(self.root / "infra/compose/compose.yaml"),
                        "exec",
                        "-T",
                        "api",
                        "python",
                        "-c",
                        BRIDGE,
                    ],
                    cwd=self.root,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                )
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
            if not select.select([self.process.stdout], [], [], self.response_timeout)[
                0
            ]:
                self.process.terminate()
                raise TimeoutError("CPU encoder response deadline exceeded")
            result = json.loads(self.process.stdout.readline())
            if result.get("error"):
                raise ValueError("CPU encoder rejected experiment input")
            from videomind.embeddings.contracts import validate_result

            validate_result(result, self.profile)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(result))
            temp.chmod(0o600)
            temp.replace(path)
        from videomind.embeddings.contracts import validate_result

        validate_result(result, self.profile)
        return result

    def close(self):
        if self.process:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=10)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
