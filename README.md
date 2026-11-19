<p align="center">
  <img src="assets/logo.svg" alt="UnlimitedLLM" width="600"/>
</p>

<p align="center">
  Universal LLM rate-limit proxy. Works with any OpenAI-compatible API.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"/></a>
  <a href="#test-coverage"><img src="https://img.shields.io/badge/tests-72%20passing-brightgreen.svg" alt="72 tests passing"/></a>
  <a href="#provider-load-tests"><img src="https://img.shields.io/badge/providers%20tested-4-blue.svg" alt="4 providers tested"/></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-async-009688.svg" alt="FastAPI"/>
</p>

<p align="center">
  <a href="#cline"><img src="https://avatars.githubusercontent.com/cline?s=64" alt="" width="20" height="20"/> Cline</a> &nbsp;·&nbsp;
  <a href="#roo-code"><img src="https://avatars.githubusercontent.com/RooCodeInc?s=64" alt="" width="20" height="20"/> Roo Code</a> &nbsp;·&nbsp;
  <a href="#opencode"><img src="https://opencode.ai/favicon.svg" alt="" width="20" height="20"/> OpenCode</a>
</p>

<p align="center">
  Via protocol adapter:
  <a href="#protocol-adapters"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.104.0/icons/codex-color.svg" alt="" width="20" height="20"/> Codex CLI</a> &nbsp;·&nbsp;
  <a href="#protocol-adapters"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.104.0/icons/claudecode-color.svg" alt="" width="20" height="20"/> Claude Code</a>
</p>

Other clients can connect if they support OpenAI-compatible chat completions and a custom base URL.

Coding agents send requests in bursts. UnlimitedLLM sits between your agent and one
configured upstream, queues requests when the window fills, and streams responses
back through `/v1/chat/completions`. Your provider's quota stays the same.

## Provider load tests

**Four providers. 340/340 HTTP 200 OK responses. Zero client-facing HTTP 429s.**

Reported results from four separate provider runs. RPM is the proxy setting used
for each experiment, not a universal limit for that provider.

| Provider | RPM | Sent | HTTP successes | Client HTTP 429s | Avg total time |
|---|---:|---:|---:|---:|---:|
| NVIDIA NIM | 40 | 100 | 100 | 0 | 21,694 ms |
| Groq | 30 | 100 | 100 | 0 | 35,721 ms |
| Gemini | 15 | 100 | 100 | 0 | 95,653 ms |
| OpenRouter | 20 | 40 | 40 | 0 | 3,355 ms |
| **Total** | | **340** | **340** | **0** | |

Gemini was the hardest run: the upstream returned both `429` and `503`, while the
client recorded 100 HTTP successes. OpenRouter had the lowest reported average.
Timings include time spent in the queue. Success is measured by HTTP status;
stream completion was not measured.

## Request handling

- **Rate limiting** — `MAX_RPM` controls how many new requests can start per window.
- **Retries** — upstream `429` and `503` responses share a bounded exponential backoff.
  Retry attempts do not acquire a new window slot.
- **Priority queue** — when the window is full, requests wait in line instead of
  failing:
  - **priority 1** — user messages (you typed it, you're waiting)
  - **priority 3** — agent loop tool calls (the bulk of traffic)
  - **priority 5** — debug dumps and huge stack traces (fire when there's room)
- **Full-duplex streaming** — SSE responses stream straight through, chunk by chunk.
- **Starvation protection** — a low-priority request stuck longer than the TTL is
  promoted so it eventually fires.
- **Backpressure** — a bounded queue rejects with `503 + Retry-After` instead of
  growing without limit.

## How It Works

```
Coding agent ──POST /v1/chat/completions──▶ UnlimitedLLM ──▶ Configured upstream
                      ▲                          │
                      └──── 200 + SSE stream ◄────┘
                        (or waits in priority queue)
```

1. A request arrives with an `X-Priority` header (1/3/5).
2. If the current 60s window has room, it fires immediately.
3. Otherwise it enters the min-heap priority queue — highest priority (lowest
   number) leaves first; same priority is FIFO.
4. When the window resets, waiting requests can claim the new slots. Finishing
   a request does not refund its slot.
5. Streaming responses relay byte-for-byte; client disconnects abort the upstream
   call and release its in-flight resources.

## Quick Start

```bash
# 1. Set your upstream key (NVIDIA NIM is the default upstream)
#    (either export it or copy .env.example → .env and fill it in)
export UPSTREAM_API_KEY=your-key-here

# 2. Install
pip install -r requirements.txt

# 3. Run
python main.py
# INFO: Uvicorn running on http://0.0.0.0:8000

# 4. Point your agent at http://localhost:8000/v1
```

Verify it's alive:

```bash
curl http://localhost:8000/status
```

To try another provider, set `UPSTREAM_BASE_URL` to its OpenAI-compatible base
URL, `UPSTREAM_DEFAULT_MODEL` and `UPSTREAM_MODELS` to model IDs it serves, and
`MAX_RPM` to your account's limit. Restart the proxy after changing `.env`.

Set `DASHBOARD_ENABLED=true` for an in-place display of window usage, in-flight
requests, queue depth, total fired, and seconds until reset. For example, in a
100-request burst at 40 RPM, the dashboard showed 40 fired / 60 queued, then
80 / 20, then 100 / 0. “Fired” means dispatched, not completed.

## Configuration

All options come from environment variables or a `.env` file (auto-loaded).

| Variable | Default | Description |
|----------|---------|-------------|
| `UPSTREAM_API_KEY` | *(required)* | API key used for upstream requests |
| `UPSTREAM_BASE_URL` | `https://integrate.api.nvidia.com/v1` | OpenAI-compatible upstream API base URL |
| `UPSTREAM_DEFAULT_MODEL` | `meta/llama-3.3-70b-instruct` | Model used when a client sends an unknown model |
| `UPSTREAM_MODELS` | *(built-in list)* | Comma-separated valid models passed through untouched |
| `REWRITE_UNKNOWN_MODELS` | `true` | `true` = rewrite unknown client models to default; `false` = pass through |
| `MAX_RPM` | `40` | Max requests per minute (matches NVIDIA free tier) |
| `WINDOW_SIZE` | `60` | Rate-limit window in seconds |
| `MAX_QUEUE` | `500` | Max queue depth before rejecting with `503 + Retry-After` |
| `RETRY_TTL` | `300` | Seconds before a queued low-priority request is promoted to priority 1 |
| `HTTP_RETRIES` | `3` | Upstream `429` and `503` retries with exponential backoff |
| `BACKOFF_BASE` | `1.0` | Backoff base seconds (sleeps 1s, 2s, 4s) |
| `CONNECT_TIMEOUT` | `30` | httpx connect timeout (s) |
| `READ_TIMEOUT` | `60` | httpx read timeout (s) |
| `WRITE_TIMEOUT` | `30` | httpx write timeout (s) |
| `POOL_TIMEOUT` | `30` | httpx pool timeout (s) |
| `MAX_STREAM_AGE` | `300` | Max age of an in-flight stream before the sweeper force-releases it |
| `SWEEP_INTERVAL` | `5` | Sweeper interval (s) |
| `LARGE_BODY_BYTES` | `262144` | Payload bytes above which a request defaults to priority 5 |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `DASHBOARD_ENABLED` | `false` | Show a live terminal dashboard and silence console logs so redraws stay in place |

The legacy `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, `NVIDIA_DEFAULT_MODEL`, and
`NVIDIA_MODELS` variables remain supported as fallbacks. When both forms are set,
the corresponding `UPSTREAM_*` variable takes precedence.

## Point Your Agent At It

### Protocol adapters

Codex CLI uses the OpenAI Responses API (`/v1/responses`); Claude Code uses the
Anthropic Messages API (`/v1/messages`). UnlimitedLLM serves `/v1/chat/completions`.
For either client, point the client at an adapter that translates its protocol,
including streamed tool calls, and configure the adapter's Chat Completions
upstream as `http://localhost:8000/v1`. These adapter paths have not been tested
end to end in this project.

### OpenCode

Add to `opencode.json` (or `~/.config/opencode/opencode.json`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "unlimitedllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "UnlimitedLLM",
      "options": {
        "baseURL": "http://localhost:8000/v1",
        "apiKey": "anything-works"
      },
      "models": {
        "nvidia/nemotron-3.5-lightning-30b-a3b": {
          "name": "Nemotron 3.5 Lightning 30B"
        }
      }
    }
  }
}
```

### Cline

1. Settings → API Provider → **OpenAI Compatible**
2. Base URL: `http://localhost:8000/v1`
3. API Key: anything (the proxy uses its configured upstream key)
4. Model: `nvidia/nemotron-3.5-lightning-30b-a3b`

### Roo Code

1. Settings → API Configuration → Provider → **OpenAI Compatible**
2. Base URL: `http://localhost:8000/v1`
3. API Key: anything
4. Model: `nvidia/nemotron-3.5-lightning-30b-a3b`

## Load Testing

`load_test.py` simulates heavy agentic traffic (100 concurrent requests, mixed
priorities, two waves) and reports status counts, leaked 429s, and queue wait times:

```bash
python load_test.py                       # full run (40 + 60 waves)
python load_test.py --total 12 --wave1 5 --wave2 7   # quick smoke
```

For local runs without calling a provider, start the included mock upstream and
point the proxy at it:

```bash
python mock_upstream.py                    # terminal 1
UPSTREAM_BASE_URL=http://localhost:9001/v1 python main.py   # terminal 2
```

## Project Layout

```
app/
  config.py        # env-driven settings
  rate_limiter.py  # sliding-window limiter + priority queue + in-flight tracking
  proxy.py         # FastAPI app, streaming upstream, 429/503 retry, validation
main.py            # entry point
load_test.py       # agentic traffic simulator
mock_upstream.py   # fake NVIDIA upstream for local testing
tests/             # 72 tests covering the full 34-case spec and regression scenarios
```

## Test Coverage

The suite implements the full 34-case spec — window resets, previous-minute
in-flight tracking, priority ordering, starvation promotion, clock skew, upstream
429/500/503 handling, client disconnects, and the compliance layer (`/v1/models`,
`/status`).

```bash
python -m pytest -q   # 72 passed
```
