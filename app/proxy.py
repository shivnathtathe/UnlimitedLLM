"""FastAPI proxy in front of an OpenAI-compatible API with rate limiting."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Tuple

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import Settings
from .rate_limiter import QueueFull, RateLimiter, Slot

log = logging.getLogger("nvidia-proxy")

DEFAULT_PRIORITY = 3
DASHBOARD_LINES = 5


def create_app(
    settings: Optional[Settings] = None, limiter: Optional[RateLimiter] = None
) -> FastAPI:
    settings = settings or Settings()
    if limiter is None:
        limiter = RateLimiter(
            max_rpm=settings.max_rpm,
            window_size=settings.window_size,
            max_queue=settings.max_queue,
            retry_ttl=settings.retry_ttl,
            sweep_interval=settings.sweep_interval,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        sweep_task = limiter.start(settings.max_stream_age)
        dashboard_task = (
            asyncio.create_task(_dashboard_loop(limiter))
            if settings.dashboard_enabled
            else None
        )
        try:
            yield
        finally:
            if dashboard_task is not None:
                dashboard_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await dashboard_task
            sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep_task

    app = FastAPI(title="Rate-Limited LLM Proxy", lifespan=lifespan)
    app.state.settings = settings
    app.state.limiter = limiter

    @app.get("/v1/models")
    async def list_models() -> JSONResponse:
        data = [
            {"id": model, "object": "model", "created": 0, "owned_by": "nvidia"}
            for model in settings.known_models
        ]
        return JSONResponse({"object": "list", "data": data})

    @app.get("/status")
    async def status() -> JSONResponse:
        return JSONResponse(limiter.status())

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        try:
            raw = await request.body()
        except Exception:
            return JSONResponse({"error": "request cancelled"}, status_code=499)
        if not raw:
            return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse({"error": "request body must be valid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)

        messages = body.get("messages")
        if not isinstance(messages, list) or len(messages) == 0:
            return JSONResponse(
                {"error": "messages must be a non-empty array"}, status_code=400
            )

        model = body.get("model")
        if isinstance(model, str):
            if model not in settings.known_models:
                log.info("unknown model %r from client", model)
                if settings.rewrite_unknown_models:
                    log.info("mapping unknown model %r to default %r", model, settings.default_model)
                    body["model"] = settings.default_model
        elif not isinstance(model, str):
            body["model"] = settings.default_model

        priority = _parse_priority(request, raw, len(raw), settings)
        stream = body.get("stream", False)

        try:
            slot = await limiter.acquire(priority)
        except QueueFull as exc:
            return JSONResponse(
                {"error": "queue full, try again later"},
                status_code=503,
                headers={"Retry-After": str(exc.retry_after)},
            )
        except asyncio.CancelledError:
            return JSONResponse(
                {"error": "request cancelled"}, status_code=503
            )

        request_id = slot.request_id
        headers = {"x-request-id": request_id}

        if stream:
            return StreamingResponse(
                _stream_events(limiter, settings, slot, body, request),
                media_type="text/event-stream",
                headers={**headers, "Cache-Control": "no-cache"},
            )

        client: Optional[httpx.AsyncClient] = None
        resp: Optional[httpx.Response] = None
        try:
            client, resp = await _open_upstream(settings, body, request_id)
            payload = await resp.aread()
            content_type = resp.headers.get("content-type", "application/json")
            return Response(
                content=payload,
                status_code=resp.status_code,
                media_type=content_type,
                headers={**headers, "Content-Type": content_type},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("non-stream upstream failure for %s", request_id)
            return JSONResponse({"error": f"upstream failure: {exc}"}, status_code=502)
        finally:
            if resp is not None:
                await resp.aclose()
            if client is not None:
                await client.aclose()
            await limiter.release(slot)

    return app


def _render_dashboard(status: dict) -> str:
    max_rpm = status["max_rpm"]
    current_rpm = status["window_count"]
    cells = 20
    filled = round(cells * current_rpm / max_rpm) if max_rpm else 0
    filled = max(0, min(cells, filled))
    bar = "█" * filled + "░" * (cells - filled)
    return "\n".join(
        (
            f"RPM            [{bar}] {current_rpm}/{max_rpm}",
            f"IN-FLIGHT      {status['in_flight']}",
            f"QUEUED         {status['queue_depth']}",
            f"TOTAL FIRED    {status['total_fired']}",
            f"WINDOW RESETS  {status['window_resets_in']:.1f}s",
        )
    )


async def _dashboard_loop(limiter: RateLimiter) -> None:
    first_frame = True
    while True:
        dashboard = _render_dashboard(limiter.status())
        if first_frame:
            frame = "".join(f"\033[2K\r{line}\n" for line in dashboard.splitlines())
            first_frame = False
        else:
            frame = f"\033[{DASHBOARD_LINES}A" + "".join(
                f"\033[2K\r{line}\n" for line in dashboard.splitlines()
            )
        sys.stdout.write(frame)
        sys.stdout.flush()
        await asyncio.sleep(1)


async def _stream_events(
    limiter: RateLimiter,
    settings: Settings,
    slot: Slot,
    body: dict,
    request: Request,
) -> AsyncGenerator[bytes, None]:
    client: Optional[httpx.AsyncClient] = None
    resp: Optional[httpx.Response] = None
    try:
        client, resp = await _open_upstream(settings, body, slot.request_id)
        if resp.status_code != 200:
            error_payload = (await resp.aread()).decode("utf-8", "replace")
            yield _sse_error(slot.request_id, resp.status_code, error_payload)
            return
        async for chunk in resp.aiter_bytes():
            if await request.is_disconnected():
                break
            yield chunk
    except asyncio.CancelledError:
        raise
    except GeneratorExit:
        pass
    except Exception as exc:
        log.exception("stream failure for %s", slot.request_id)
        yield _sse_error(slot.request_id, 500, f"stream failure: {exc}")
    finally:
        if resp is not None:
            await resp.aclose()
        if client is not None:
            await client.aclose()
        await limiter.release(slot)


async def _open_upstream(
    settings: Settings, body: dict, request_id: str
) -> Tuple[httpx.AsyncClient, httpx.Response]:
    headers = {
        "Authorization": f"Bearer {settings.upstream_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-request-id": request_id,
    }
    url = settings.upstream_url()
    kwargs: dict = {"timeout": settings.httpx_timeout()}
    if settings.transport is not None:
        kwargs["transport"] = settings.transport
    for attempt in range(settings.http_retries + 1):
        client = httpx.AsyncClient(**kwargs)
        req = client.build_request("POST", url, json=body, headers=headers)
        resp = await client.send(req, stream=True)
        if resp.status_code in {429, 503} and attempt < settings.http_retries:
            await resp.aclose()
            await client.aclose()
            backoff = settings.backoff_base * (2 ** attempt)
            log.warning(
                "upstream %d for %s, retrying in %.1fs",
                resp.status_code,
                request_id,
                backoff,
            )
            await asyncio.sleep(backoff)
            continue
        return client, resp
    raise RuntimeError("unreachable")


def _sse_error(request_id: str, status_code: int, detail: str) -> bytes:
    payload = json.dumps({"error": {"message": detail, "type": "upstream_error", "code": status_code}})
    return f"data: {payload}\n\n".encode("utf-8")


def _parse_priority(request: Request, raw: bytes, size: int, settings: Settings) -> int:
    header = request.headers.get("X-Priority", "")
    if header:
        try:
            parsed = int(header)
        except ValueError:
            parsed = DEFAULT_PRIORITY
        return max(1, min(5, parsed))
    if size > settings.large_body_bytes:
        return 5
    return DEFAULT_PRIORITY
