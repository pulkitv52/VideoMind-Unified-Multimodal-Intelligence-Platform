"""Offline CPU model adapter; imports heavy dependencies only inside the service."""

import base64
import hashlib
import io
import json
import math
from pathlib import Path
from videomind.embeddings.budget import split_to_budget
from videomind.embeddings.contracts import validate_vector


class Runtime:
    def __init__(self):
        import torch
        from sentence_transformers import SentenceTransformer
        from videomind.embeddings.profile import installed_profile

        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        self.profile = installed_profile()
        root = Path("/models/embedding")
        manifest = json.loads((root / "manifest.json").read_text())
        for name, sha in manifest.items():
            with (root / name).open("rb") as handle:
                actual = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual != sha:
                raise ValueError("checkpoint identity")
        self.model = SentenceTransformer(
            str(root),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"torch_dtype": torch.float32},
        )
        self.model.eval()
        self.model[0].processing_kwargs = {
            "text": {"truncation": False},
            "video": {"do_sample_frames": False, "add_timestamps": False},
        }
        from transformers import AutoProcessor

        self.processor = AutoProcessor.from_pretrained(
            str(root), local_files_only=True, trust_remote_code=False
        )

    def encode(self, kind, content, title="", query=False, configuration=None):
        recipe = configuration or self.profile
        import numpy as np
        import soundfile as sf
        from PIL import Image

        if kind == "text":
            if not isinstance(content, str) or not content or len(content) > 200000:
                raise ValueError("text bounds")
            units = list(content)
        elif kind == "image":
            units = [content]
        elif kind == "video":
            if not isinstance(content, list) or not 1 <= len(content) <= 301:
                raise ValueError("frame bounds")
            units = content
        elif kind == "audio":
            samples, rate = sf.read(
                io.BytesIO(base64.b64decode(content, validate=True)), dtype="float32"
            )
            if (
                rate != 16000
                or samples.ndim != 1
                or not 1 <= len(samples) <= 320000
                or not np.isfinite(samples).all()
            ):
                raise ValueError("audio bounds")
            units = samples
        else:
            raise ValueError("kind")

        def image(encoded):
            data = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(data)) as im:
                if im.width * im.height > 16000000:
                    raise ValueError("image bounds")
                return im.convert("RGB").copy()

        def payload(part):
            if kind == "text":
                raw = "".join(part)
                return (
                    recipe.query_prompt.format(query=raw)
                    if query
                    else recipe.document_prompt.format(title=title[:300], content=raw)
                )
            if kind == "image":
                return {"image": image(part[0])}
            if kind == "video":
                return {"video": np.stack([np.asarray(image(x)) for x in part])}
            return {
                "audio": {
                    "array": np.asarray(part, dtype=np.float32),
                    "sampling_rate": 16000,
                }
            }

        def tokens(part):
            value = payload(part)
            kwargs = {"return_tensors": "pt", "text_kwargs": {"truncation": False}}
            if kind == "text":
                kwargs["text"] = value
            elif kind == "image":
                kwargs["images"] = value["image"]
            elif kind == "video":
                kwargs["videos"] = [value["video"]]
                kwargs["videos_kwargs"] = {
                    "do_sample_frames": False,
                    "add_timestamps": False,
                }
            else:
                kwargs["audio"] = value["audio"]["array"]
                kwargs["sampling_rate"] = 16000
            return int(self.processor(**kwargs)["attention_mask"].sum())

        if query:
            if tokens(units) > 7500:
                raise ValueError("query budget")
            parts = [units]
        else:
            parts = split_to_budget(units, tokens)
        if len(parts) > 64:
            raise ValueError("part bounds")
        results = []
        offset = 0
        for part in parts:
            value = payload(part)
            vector = self.model.encode(
                [value],
                normalize_embeddings=True,
                batch_size=1,
                show_progress_bar=False,
            )[0].tolist()
            validate_vector(vector)
            results.append(
                {
                    "start_unit": offset,
                    "end_unit": offset + len(part),
                    "tokens": tokens(part),
                    "vector": vector,
                }
            )
            offset += len(part)
        return {
            "profile": recipe.fingerprint,
            "parts": results,
            "units": len(units),
        }
