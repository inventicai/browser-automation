"""FastAPI orchestrator: extension WebSocket + dev HTTP task runner."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from .agent.context import AgentDeps
from .agent.harness import AgentHarness
from .cdp.relay import CDPRelay
from .cdp.extension_relay import ExtensionCDPRelay
from .cdp.watchdog import CDPWatchdog
from .session.auth import validate_token
from .session.observation_validator import validate_observation
from .session.registry import SessionRegistry

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("brotto.main")

# Quiet noisy third-party loggers
for _noisy in ("httpx", "httpcore", "websockets", "uvicorn.access"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Brotto Orchestrator", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

registry = SessionRegistry()
harness = AgentHarness()


@app.get("/health")
async def health():
    log.debug("health check")
    from .agent.harness import _MODEL
    return {"status": "ok", "service": "brotto-orchestrator", "version": "2.0.0", "model": _MODEL}


# ---------------------------------------------------------------------------
# Session creation — called by the extension before connecting WS
# ---------------------------------------------------------------------------

@app.post("/v1/sessions")
async def create_session(request: Request):
    session_id = str(uuid.uuid4())
    registry.get_or_create(session_id)
    ws_url = f"ws://localhost:8000/ws/ext/{session_id}"
    log.info("session created  session_id=%s  ws_url=%s", session_id, ws_url)
    return JSONResponse(status_code=201, content={
        "session_id": session_id,
        "websocket_url": ws_url,
        "server_url": "http://localhost:8000",
    })


# ---------------------------------------------------------------------------
# Extension WebSocket — observe/act loop driven by the browser extension
# ---------------------------------------------------------------------------

@app.websocket("/ws/ext/{session_id}")
async def websocket_extension(websocket: WebSocket, session_id: str):
    """Extension relay WebSocket.

    Extension → server: task_start | observation | human_reply | ping
    Server → extension: observe | action | step_progress | ask_human | task_result | pong
    """
    await websocket.accept()
    log.info("[%s] extension connected", session_id)

    obs_queue: asyncio.Queue = asyncio.Queue()
    human_queue: asyncio.Queue = asyncio.Queue()
    # D9: the per-session tracker is held by the registry, so a
    # reconnect with the same session_id resumes dedup correctly.
    in_seq_tracker = registry.get_or_create_in_seq(session_id)
    legacy_warned = False

    async def ws_send(msg: dict) -> None:
        msg_type = msg.get("type", "?")
        try:
            payload = json.dumps(msg)
            await websocket.send_text(payload)
            if msg_type == "action":
                log.debug("[%s] → action  %s", session_id, json.dumps(msg.get("action", {}))[:120])
            elif msg_type == "observe":
                log.debug("[%s] → observe", session_id)
            else:
                log.debug("[%s] → %s  %s", session_id, msg_type, payload[:120])
        except Exception as exc:
            log.warning("[%s] ws_send failed  type=%s  err=%s", session_id, msg_type, exc)

    # Wait for task_start
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
        msg = json.loads(raw)
        log.debug("[%s] ← %s", session_id, raw[:200])
        if msg.get("type") != "task_start":
            log.warning("[%s] expected task_start, got %s — closing", session_id, msg.get("type"))
            await websocket.close(code=4000)
            return
        task = msg.get("task", "").strip()
        if not task:
            log.warning("[%s] task_start with empty task — closing", session_id)
            await websocket.close(code=4000)
            return
        log.info("[%s] task_start  task=%r", session_id, task[:100])
    except asyncio.TimeoutError:
        log.warning("[%s] timed out waiting for task_start", session_id)
        await websocket.close(code=4000)
        return
    except Exception as exc:
        log.error("[%s] error receiving task_start: %s", session_id, exc)
        await websocket.close(code=4000)
        return

    eval_queue: asyncio.Queue = asyncio.Queue()
    relay = ExtensionCDPRelay(ws_send, obs_queue, eval_queue, session_id)
    deps = AgentDeps(
        user_id=session_id,
        task=task,
        task_id=session_id,
        cdp=relay,
        ws_send=ws_send,
        human_input_queue=human_queue,
    )

    agent_task = asyncio.create_task(harness.run(deps))
    log.info("[%s] agent task started", session_id)

    try:
        while not agent_task.done():
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                incoming = json.loads(raw)
                t = incoming.get("type")

                # D9 — validate observation sequence tracking before
                # enqueueing. Duplicates are dropped here so the agent
                # loop never sees them.
                decision = validate_observation(
                    incoming, in_seq_tracker, is_legacy_warned=legacy_warned,
                )
                if not decision.accept:
                    if decision.reason == "legacy_no_seq":
                        legacy_warned = True
                    else:
                        log.debug(
                            "[%s] dropped %s  seq=%s  reason=%s",
                            session_id, t, incoming.get("seq"), decision.reason,
                        )
                        continue

                if t == "observation":
                    n = len(incoming.get("axTargets", []))
                    log.debug(
                        "[%s] ← observation  url=%s  ax_targets=%d",
                        session_id, incoming.get("url", "")[:80], n,
                    )
                    await obs_queue.put(incoming)
                elif t == "observation_error":
                    log.warning("[%s] ← observation_error  err=%s", session_id, incoming.get("error"))
                    await obs_queue.put({"url": "", "title": "", "axTargets": []})
                elif t == "evaluate_result":
                    log.debug("[%s] ← evaluate_result  len=%d", session_id, len(incoming.get("value", "")))
                    await eval_queue.put(incoming.get("value", ""))
                elif t == "human_reply":
                    log.info("[%s] ← human_reply", session_id)
                    await human_queue.put(incoming.get("content", ""))
                elif t == "ping":
                    await ws_send({"type": "pong"})
                else:
                    log.debug("[%s] ← unknown type=%s", session_id, t)
            except asyncio.TimeoutError:
                continue
            except json.JSONDecodeError as exc:
                log.warning("[%s] bad JSON from extension: %s", session_id, exc)
            except Exception as exc:
                # WebSocket close frames (1000/1001/1005) surface as ConnectionClosed
                if "ConnectionClosed" in type(exc).__name__ or "CloseCode" in str(exc):
                    log.info("[%s] websocket closed: %s", session_id, exc)
                else:
                    log.error("[%s] receive loop error: %s", session_id, exc)
                break
    except WebSocketDisconnect:
        log.info("[%s] extension disconnected mid-task", session_id)
        agent_task.cancel()
    finally:
        if not agent_task.done():
            agent_task.cancel()
        try:
            result = await agent_task
            log.info("[%s] task finished  status=%s  summary=%r", session_id, result.status, result.summary[:80])
            await ws_send({"type": "task_result", "result": result.model_dump()})
        except asyncio.CancelledError:
            log.info("[%s] agent task cancelled", session_id)
        except Exception as exc:
            log.error("[%s] agent task raised: %s", session_id, exc, exc_info=True)
            await ws_send({"type": "task_error", "error": str(exc)})
        log.info("[%s] session closed", session_id)


# ---------------------------------------------------------------------------
# Playwright WebSocket — for headless / desktop connector mode
# ---------------------------------------------------------------------------

@app.websocket("/ws/{user_id}")
async def websocket_agent(websocket: WebSocket, user_id: str):
    token = websocket.headers.get("authorization", "").replace("Bearer ", "")
    if not validate_token(token):
        log.warning("[%s] rejected — bad token", user_id)
        await websocket.close(code=4001)
        return

    await websocket.accept()
    log.info("[%s] playwright client connected", user_id)
    session = registry.get_or_create(user_id)
    human_input_queue: asyncio.Queue = asyncio.Queue()

    async def ws_send(msg: dict) -> None:
        try:
            await websocket.send_text(json.dumps(msg))
            log.debug("[%s] → %s", user_id, msg.get("type"))
        except Exception as exc:
            log.warning("[%s] ws_send failed: %s", user_id, exc)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")
            log.debug("[%s] ← %s", user_id, msg_type)

            if msg_type == "ping":
                await ws_send({"type": "pong"})

            elif msg_type == "submit_task":
                session.cancel_current_task()
                task_text = msg.get("task", "")
                start_url = msg.get("start_url", "about:blank")
                log.info("[%s] submit_task  task=%r  start_url=%s", user_id, task_text[:80], start_url)

                async def _run_task(task: str, start_url: str) -> None:
                    from .dev.playwright_browser import PlaywrightBrowser
                    task_id = str(uuid.uuid4())
                    browser = PlaywrightBrowser()
                    try:
                        await browser.launch(headless=False, url=start_url or "about:blank")
                        cdp = CDPRelay(browser)
                        deps = AgentDeps(
                            user_id=user_id,
                            task=task,
                            task_id=task_id,
                            cdp=cdp,
                            ws_send=ws_send,
                            human_input_queue=human_input_queue,
                        )
                        watchdog = CDPWatchdog(cdp, on_dead=lambda: ws_send({"type": "cdp_dead"}))
                        await watchdog.start()
                        try:
                            result = await harness.run(deps)
                        finally:
                            watchdog.stop()
                        await ws_send({"type": "task_result", "result": result.model_dump()})
                    except asyncio.CancelledError:
                        await ws_send({"type": "task_cancelled"})
                    except Exception as exc:
                        log.error("[%s] task error: %s", user_id, exc, exc_info=True)
                        await ws_send({"type": "task_error", "error": str(exc)})
                    finally:
                        await browser.close()

                t = asyncio.create_task(_run_task(task_text, start_url))
                session.current_task = t

            elif msg_type == "human_reply":
                await human_input_queue.put(msg.get("content", ""))

            elif msg_type == "cancel_task":
                session.cancel_current_task()
                await ws_send({"type": "task_cancelled"})

    except WebSocketDisconnect:
        log.info("[%s] playwright client disconnected", user_id)
        registry.mark_disconnected(user_id)


# ---------------------------------------------------------------------------
# Dev HTTP — headless task runner
# ---------------------------------------------------------------------------

@app.post("/run")
async def run_task(request: Request):
    body = await request.json()
    task = body.get("task", "")
    start_url = body.get("start_url", "about:blank")
    log.info("/run  task=%r  start_url=%s", task[:80], start_url)

    if not task:
        return JSONResponse(status_code=400, content={"error": "task required"})

    from .dev.playwright_browser import PlaywrightBrowser
    browser = PlaywrightBrowser()

    async def ws_send(msg: dict) -> None:
        log.info("[run] → %s  %s", msg.get("type"), json.dumps(msg)[:200])

    try:
        await browser.launch(headless=True, url=start_url)
        cdp = CDPRelay(browser)
        task_id = str(uuid.uuid4())
        deps = AgentDeps(user_id="http-dev", task=task, task_id=task_id, cdp=cdp, ws_send=ws_send)
        result = await harness.run(deps)
        return JSONResponse(content=result.model_dump())
    except Exception as exc:
        log.error("/run error: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(exc)})
    finally:
        await browser.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
