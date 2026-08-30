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
from .policy import Policy, UserPolicy, load_policy, merge as merge_policy

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_LEVEL = os.getenv("BROTTO_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("brotto.main")

# ponytail: match the sidepanel's MAX_TASK_CHARS. Anything over this is
# logged as a warning (defense in depth) but NOT blocked — the sidepanel
# already shows a confirm() dialog, and the user is the final authority
# on what they want the agent to do.
MAX_TASK_CHARS = 1000

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

# ponytail: hydrate persisted user policies so the in-memory cache
# survives a server restart. Without this, GET /v1/policy right after
# boot would return floor-only even for returning users. Loaded once
# at startup; written to disk by `persist_user_policy()` below.
try:
    from .policy import persist as _user_policy_persist
    _loaded = registry.hydrate_user_policies(_user_policy_persist.load_all())
    _dir = _user_policy_persist.directory_path()
    log.info(
        "user-policy persistence: dir=%s  hydrated=%d",
        _dir.resolve(), _loaded,
    )
except Exception as exc:
    log.warning("user-policy hydrate failed (continuing without): %s", exc)

# Floor policy: loaded once at startup. Used as the org-wide minimum that
# user policies can raise but never lower. None when no file is configured.
FLOOR_POLICY: Policy | None = load_policy()
if FLOOR_POLICY is not None:
    log.info("loaded floor policy  mode=%s  blacklist=%d",
             FLOOR_POLICY.mode, len(FLOOR_POLICY.blacklist))
else:
    log.info("no floor policy file (BROTTO_POLICY_FILE unset and ./policy.json absent); user toggle is authoritative")


@app.get("/health")
async def health():
    log.debug("health check")
    from .agent.harness import _MODEL
    policy_summary = None
    if FLOOR_POLICY is not None:
        policy_summary = {
            "mode": FLOOR_POLICY.mode,
            "blacklist_count": len(FLOOR_POLICY.blacklist),
            "first_time_seen_prompt": FLOOR_POLICY.first_time_seen_prompt,
            "sensitive_actions_count": len(FLOOR_POLICY.sensitive_actions),
        }
    return {
        "status": "ok",
        "service": "brotto-orchestrator",
        "version": "2.0.0",
        "model": _MODEL,
        "policy": policy_summary,
    }


def _persist_user_policy(user_key: str, payload: dict | None) -> None:
    """Best-effort write of the user's last-known policy to disk.

    Calls `save_if_changed` so a no-op Save click (same content) does
    NOT bump the on-disk mtime — the sidepanel's "Last verified" badge
    stays accurate and we avoid needless disk IO. A WARNING is logged
    on disk failures; the in-memory cache still works for the current
    run, but the next restart will lose the change.
    """
    if payload is None:
        return
    try:
        from .policy import persist as _user_policy_persist
        wrote = _user_policy_persist.save_if_changed(user_key, payload)
        if wrote:
            log.info(
                "user-policy saved  user_key=%s  blacklist=%s  mode=%s",
                user_key,
                payload.get("blacklist"),
                payload.get("mode"),
            )
        # else: silent no-op save; this is the common case when the
        # user clicks Save without changing anything.
    except Exception as exc:
        log.warning("failed to persist user policy for %s: %s", user_key, exc)


# ponytail: sidepanel fetches this on init so the CONTEXT cell shows the
# right baseline (the server's current model's window) before any
# step_progress arrives. The frontend never computes the percentage —
# the harness emits a pre-computed `pct` on every step.
@app.get("/context")
async def context_limit():
    from .agent.harness import _MODEL, _CONTEXT_WINDOW_TOKENS
    return {"model": _MODEL, "window": _CONTEXT_WINDOW_TOKENS}


# ponytail: GET /v1/policy returns the EFFECTIVE policy the server will
# enforce for this caller — union of floor + last-known user policy. The
# extension calls this on Settings open so the sidepanel can render the
# floor as a locked read-only block alongside the user's editable list.
# Unauthenticated (same as /health) — payload only contains domain lists,
# not secrets; this is fine for the demo. Add auth before any production
# deployment.
@app.get("/v1/policy")
async def get_effective_policy(request: Request):
    from .policy import UserPolicy
    # Caller identity: prefer explicit query, fall back to client IP
    # (SessionRegistry tracks per-IP for the lifetime of the server).
    caller = request.query_params.get("user_id") or (
        request.client.host if request.client else "unknown"
    )
    user_payload = registry.get_user_policy_payload(caller)
    user_pol: UserPolicy | None = None
    if isinstance(user_payload, dict):
        try:
            user_pol = UserPolicy.model_validate(user_payload)
        except Exception:
            user_pol = None
    effective = merge_policy(FLOOR_POLICY, user_pol)
    return JSONResponse(content={
        "mode": effective.mode,
        "blacklist": effective.blacklist,
        "sensitive_actions": effective.sensitive_actions,
        "source": {
            "floor": list(FLOOR_POLICY.blacklist) if FLOOR_POLICY else [],
            "user": list(user_pol.blacklist) if user_pol else [],
        },
        "caller": caller,
    })


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


# ponytail: separate HTTP endpoint for save-time notification. The
# WS-based `policy_acknowledged` only works while a task is in flight;
# this one logs even when the user clicks Save with no task running.
@app.post("/v1/policy_ack")
async def policy_ack(request: Request):
    body = await request.json()
    settings = body.get("settings") or {}
    user_id = body.get("user_id") or request.client.host if request.client else "unknown"
    mode = settings.get("mode")
    blacklist = settings.get("blacklist") or []
    # Mirror on the session registry so a later GET /v1/policy returns
    # this user's view (handles the "Save with no WS open" case from
    # the audit work earlier). Persist to disk too.
    snapshot = {"mode": mode, "blacklist": blacklist}
    registry.set_user_policy(user_id, snapshot)
    _persist_user_policy(user_id, snapshot)
    log.warning(
        "[%s] POLICY: user saved settings  mode=%s  blacklist=%s",
        user_id, mode, blacklist,
    )
    try:
        from .agent.run_logger import append_policy_event
        append_policy_event(
            f"client-{user_id}",
            step=None, kind="policy_acknowledged",
            domain=None, action=None,
            decision=f"mode={mode}  blacklist={blacklist}",
        )
    except Exception as exc:
        log.warning("failed to persist policy_acknowledged: %s", exc)
    return JSONResponse(content={"ok": True})


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
        if len(task) > MAX_TASK_CHARS:
            # Defense in depth — the sidepanel already showed a confirm().
            # Server logs so the audit trail records the unusually-long
            # input. No block: the user's intent is the final word.
            log.warning(
                "[%s] task_start exceeds %d chars (%d) — prompt-injection risk",
                session_id, MAX_TASK_CHARS, len(task),
            )
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

    # ponytail: key policy storage by CLIENT IP, not session_id. session_id
    # is fresh per /v1/sessions call, so anything stashed under it is dead
    # the moment the next task opens a new session. IP is the closest thing
    # to "user identity" we have without auth, and matches the key used
    # by /v1/policy GET and /v1/policy_ack — making the three callers
    # finally agree.
    client_host = websocket.client.host if websocket.client else "unknown"

    # Merge floor + user policy. Server floor wins on mode; lists union.
    user_policy_payload = msg.get("user_policy")
    user_policy: Policy | None = None
    if isinstance(user_policy_payload, dict):
        try:
            user_policy = UserPolicy.model_validate(user_policy_payload)
        except Exception as exc:
            log.warning("[%s] invalid user_policy, ignoring: %s", session_id, exc)
    # Stash under IP so `GET /v1/policy` returns this user's view even
    # if the sidepanel opens settings after the WS closes. Persist to
    # disk under hashed IP so the view survives a server restart.
    if isinstance(user_policy_payload, dict):
        registry.set_user_policy(client_host, user_policy_payload)
        _persist_user_policy(client_host, user_policy_payload)
    effective_policy = merge_policy(FLOOR_POLICY, user_policy)
    log.info("[%s] effective_policy  mode=%s  blacklist=%d",
             session_id, effective_policy.mode,
             len(effective_policy.blacklist))

    deps = AgentDeps(
        user_id=session_id,
        task=task,
        task_id=session_id,
        cdp=relay,
        ws_send=ws_send,
        policy=effective_policy,
        human_input_queue=human_queue,
    )

    agent_task = asyncio.create_task(harness.run(deps))
    log.info("[%s] agent task started", session_id)

    # ponytail: one-shot WS frame so the sidepanel knows the EFFECTIVE
    # policy the server is about to enforce (floor + user merged). Without
    # this the sidepanel has no way to render "X domains enforced by your
    # organisation" — it would only see its own saved list.
    try:
        await ws_send({
            "type": "policy_effective",
            "mode": effective_policy.mode,
            "blacklist": effective_policy.blacklist,
            "sensitive_actions": effective_policy.sensitive_actions,
            "source": {
                "floor": list(FLOOR_POLICY.blacklist) if FLOOR_POLICY else [],
                "user": list(user_policy.blacklist) if user_policy else [],
            },
        })
    except Exception as exc:
        log.warning("[%s] failed to send policy_effective: %s", session_id, exc)

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
                elif t == "revoke":
                    # ponytail: user clicked Revoke on a prior approval within
                    # the post-approval window. Clear the first-time-seen
                    # cache so the next step re-prompts. With deny-aborts-task
                    # semantics, approved actions can't be "undone" — the task
                    # is over once an action runs. Revoke just resets what
                    # the next task would do.
                    log.warning(
                        "[%s] POLICY: user REVOKED prior approval — clearing seen_first_time",
                        session_id,
                    )
                    try:
                        deps.seen_first_time.clear()
                    except Exception as exc:
                        log.warning("[%s] revoke state-clear failed: %s", session_id, exc)
                    await ws_send({"type": "policy_revoked"})
                elif t == "ping":
                    await ws_send({"type": "pong"})
                elif t == "policy_acknowledged":
                    # Extension user clicked Save in sidepanel Settings.
                    # Log the full new payload so the server has a record
                    # independent of any task_start.
                    settings = incoming.get("settings") or {}
                    # Update the in-memory mirror so GET /v1/policy returns
                    # the just-saved view without waiting for the next
                    # task_start. Persist to disk too. Keyed by IP so it
                    # survives a session restart — see the ponytail note
                    # at the task_start handler above.
                    snapshot = {
                        "mode": settings.get("mode"),
                        "blacklist": settings.get("blacklist") or [],
                    }
                    registry.set_user_policy(client_host, snapshot)
                    _persist_user_policy(client_host, snapshot)
                    log.warning(
                        "[%s] POLICY: user saved settings  mode=%s  blacklist=%s",
                        session_id,
                        settings.get("mode"),
                        settings.get("blacklist"),
                    )
                    try:
                        from .agent.run_logger import append_policy_event
                        append_policy_event(
                            session_id,
                            step=None, kind="policy_acknowledged",
                            domain=None, action=None,
                            decision=(
                                f"mode={settings.get('mode')}  "
                                f"blacklist={settings.get('blacklist')}"
                            ),
                        )
                    except Exception as exc:
                        log.warning("[%s] failed to persist policy_acknowledged: %s", session_id, exc)
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
                user_policy_payload = msg.get("user_policy")
                user_policy: Policy | None = None
                if isinstance(user_policy_payload, dict):
                    try:
                        user_policy = UserPolicy.model_validate(user_policy_payload)
                    except Exception as exc:
                        log.warning("[%s] invalid user_policy, ignoring: %s", user_id, exc)
                effective_policy = merge_policy(FLOOR_POLICY, user_policy)
                log.info("[%s] submit_task  task=%r  start_url=%s  effective_mode=%s",
                         user_id, task_text[:80], start_url, effective_policy.mode)
                log.info("[%s] effective_policy  mode=%s  blacklist=%d",
                         user_id, effective_policy.mode,
                         len(effective_policy.blacklist))

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
                            policy=effective_policy,
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
    user_policy_payload = body.get("user_policy")
    user_policy: Policy | None = None
    if isinstance(user_policy_payload, dict):
        try:
            user_policy = UserPolicy.model_validate(user_policy_payload)
        except Exception as exc:
            log.warning("/run: invalid user_policy, ignoring: %s", exc)
    effective_policy = merge_policy(FLOOR_POLICY, user_policy)
    log.info("/run  task=%r  start_url=%s  effective_mode=%s",
             task[:80], start_url, effective_policy.mode)

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
        deps = AgentDeps(
            user_id="http-dev",
            task=task,
            task_id=task_id,
            cdp=cdp,
            ws_send=ws_send,
            policy=effective_policy,
        )
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
