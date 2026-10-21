"""Private bounded priority inference server. No database/storage credentials."""

import asyncio
import hmac
import os
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from videomind.embeddings.profile import installed_profile
from videomind.embeddings.contracts import EmbeddingProfile, validate_prompts


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text", "image", "video", "audio"]
    content: str | list[str]
    title: str = Field(default="", max_length=300)
    query: bool = False
    configuration: EmbeddingProfile | None = None
    profile: str = Field(min_length=64, max_length=64)


@asynccontextmanager
async def lifespan(app):
    queue = asyncio.PriorityQueue(maxsize=16)
    app.state.queue = queue
    app.state.loaded = False
    app.state.error = None
    app.state.counter = 0
    app.state.profile = installed_profile()
    app.state.token = Path("/run/secrets/embedding_token").read_text().strip()

    async def work():
        runtime = None
        while True:
            _, _, body, future = await queue.get()
            if future.cancelled():
                queue.task_done()
                continue
            watchdog = threading.Timer(590, lambda: os._exit(70))
            watchdog.daemon = True
            watchdog.start()
            try:
                if runtime is None:
                    from videomind.embeddings.runtime import Runtime

                    runtime = await asyncio.to_thread(Runtime)
                    app.state.loaded = True
                result = await asyncio.to_thread(
                    runtime.encode,
                    body.kind,
                    body.content,
                    body.title,
                    body.query,
                    body.configuration,
                )
                if not future.done():
                    future.set_result(result)
            except Exception:
                if not future.done():
                    future.set_exception(ValueError("INFERENCE_FAILED"))
            finally:
                watchdog.cancel()
                queue.task_done()

    task = asyncio.create_task(work())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {
        "ready": True,
        "loaded": app.state.loaded,
        "queued": app.state.queue.qsize(),
        "profile": app.state.profile.model_dump(),
        "fingerprint": app.state.profile.fingerprint,
    }


@app.post("/encode")
async def encode(request: Request):
    if not hmac.compare_digest(
        request.headers.get("authorization", ""), "Bearer " + app.state.token
    ):
        raise HTTPException(401)
    if int(request.headers.get("content-length", "0")) > 32 * 1024**2:
        raise HTTPException(413)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 32 * 1024**2:
            raise HTTPException(413)
    try:
        body = Input.model_validate_json(data)
    except Exception:
        raise HTTPException(422, "Invalid input")
    recipe = body.configuration or app.state.profile
    if recipe.model_dump(
        exclude={"query_prompt", "document_prompt"}
    ) != app.state.profile.model_dump(exclude={"query_prompt", "document_prompt"}):
        raise HTTPException(409, "Unsupported model/runtime profile")
    try:
        validate_prompts(recipe)
    except ValueError:
        raise HTTPException(422, "Invalid prompt template")
    if body.profile != recipe.fingerprint:
        raise HTTPException(409, "Profile mismatch")
    if body.query and body.kind not in {"text", "image"}:
        raise HTTPException(422)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    app.state.counter += 1
    try:
        app.state.queue.put_nowait(
            (0 if body.query else 1, app.state.counter, body, future)
        )
    except asyncio.QueueFull:
        raise HTTPException(429, "Inference queue full")
    try:
        return await asyncio.wait_for(future, timeout=600)
    except TimeoutError:
        raise HTTPException(504, "Inference deadline")
    except ValueError:
        raise HTTPException(422, "INFERENCE_FAILED")
