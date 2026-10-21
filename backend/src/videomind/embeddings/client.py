"""Small authenticated client, usable without importing Torch."""

import json
from pathlib import Path
from urllib.request import Request, urlopen
from videomind.embeddings.contracts import (
    EmbeddingProfile,
    validate_vector,
    validate_result,
)


class Client:
    def __init__(
        self, url="http://embedding:8090", token_file="/run/secrets/embedding_token"
    ):
        self.url = url
        self.token_file = token_file

    def health(self):
        with urlopen(self.url + "/health", timeout=5) as r:
            return json.load(r)

    def profile(self):
        return EmbeddingProfile.model_validate(self.health()["profile"])

    def encode(self, profile, kind, content, title="", query=False, configuration=None):
        token = Path(self.token_file).read_text().strip()
        request = Request(
            self.url + "/encode",
            data=json.dumps(
                {
                    "profile": profile,
                    "kind": kind,
                    "content": content,
                    "title": title[:300],
                    "query": query,
                    "configuration": configuration,
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
        )
        with urlopen(request, timeout=610) as response:
            result = json.load(response)
        validate_result(result, profile)
        if result["profile"] != profile:
            raise ValueError("profile mismatch")
        offset = 0
        for part in result["parts"]:
            validate_vector(part["vector"])
            if (
                part["tokens"] > 7500
                or part["start_unit"] != offset
                or part["end_unit"] <= offset
            ):
                raise ValueError("invalid split")
            offset = part["end_unit"]
        if not offset or offset != result["units"]:
            raise ValueError("incomplete coverage")
        return result
