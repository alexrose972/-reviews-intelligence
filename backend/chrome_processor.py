"""
Chrome browser job processor — queue management + computer-use execution.

Runs as a background asyncio task in FastAPI (queue/timeout management).
Set CHROME_RUNNER_ENABLED=true on the local Mac to enable actual execution.
"""

import asyncio
import base64
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_

from .database import AsyncSessionLocal, ChromeJob, ScanRun
from .chrome_instructions import build_chrome_instruction

log = logging.getLogger("chrome_processor")

TIMEOUT_MINUTES = int(os.environ.get("CHROME_JOB_TIMEOUT_MINUTES", "15"))
POLL_INTERVAL = 10
WEBHOOK_URL = os.environ.get(
    "RAILWAY_PUBLIC_DOMAIN",
    "https://reviews-intelligence-production.up.railway.app",
).rstrip("/")
WEBHOOK_SECRET = os.environ.get("BROWSER_WEBHOOK_SECRET", "")
RUNNER_ENABLED = os.environ.get("CHROME_RUNNER_ENABLED", "").lower() == "true"


async def chrome_job_processor():
    """Background asyncio task — started by FastAPI on startup."""
    log.info("Chrome processor started (runner_enabled=%s)", RUNNER_ENABLED)
    while True:
        try:
            if not RUNNER_ENABLED:
                # No local runner is consuming the queue (e.g. on Railway).
                # Idle quietly and leave jobs honestly 'queued' rather than
                # flipping them to a fake 'running' that then times out.
                await asyncio.sleep(60)
                continue
            await _handle_timeouts()
            running = await _get_running_job()
            if running:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            job = await _get_next_queued_job()
            if not job:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            await process_chrome_job(job)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("Chrome processor error: %s", exc, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)


async def _handle_timeouts():
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChromeJob).where(
                and_(ChromeJob.status == "running", ChromeJob.timeout_at <= now)
            )
        )
        for job in result.scalars().all():
            log.warning("Chrome job %s timed out", job.id)
            job.status = "timeout"
            job.error = f"Timed out after {TIMEOUT_MINUTES}m"
            job.completed_at = now
            run = await db.get(ScanRun, job.scan_id)
            if run:
                run.chrome_job_status = "timeout"
                run.chrome_job_completed_at = now
                run.chrome_error = job.error
        await db.commit()


async def _get_running_job():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChromeJob).where(ChromeJob.status == "running").limit(1)
        )
        return result.scalar_one_or_none()


async def _get_next_queued_job():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChromeJob)
            .where(ChromeJob.status == "queued")
            .order_by(ChromeJob.priority.desc(), ChromeJob.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _update_job(job_id, **kwargs):
    async with AsyncSessionLocal() as db:
        job = await db.get(ChromeJob, job_id)
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            await db.commit()


async def _update_scan(scan_id, **kwargs):
    async with AsyncSessionLocal() as db:
        run = await db.get(ScanRun, scan_id)
        if run:
            for k, v in kwargs.items():
                setattr(run, k, v)
            await db.commit()


async def process_chrome_job(job: ChromeJob):
    """Mark job running and dispatch instruction to Chrome.

    Only reached when RUNNER_ENABLED is true — the processor loop idles
    otherwise, leaving jobs honestly 'queued' for a runner to pick up.
    """
    now = datetime.utcnow()
    await _update_job(
        job.id,
        status="running",
        started_at=now,
        timeout_at=now + timedelta(minutes=TIMEOUT_MINUTES),
        attempts=job.attempts + 1,
    )
    await _update_scan(job.scan_id, chrome_job_status="running", chrome_job_started_at=now)

    instruction = build_chrome_instruction(
        brand=job.brand_name,
        base_url=job.base_url,
        scan_id=str(job.scan_id),
        webhook_url=WEBHOOK_URL,
        webhook_secret=WEBHOOK_SECRET,
    )

    try:
        success = await send_to_claude_in_chrome(instruction, str(job.scan_id))
        if not success:
            raise RuntimeError("Agent returned failure")
        log.info("Chrome job %s dispatched", job.id)
    except Exception as exc:
        log.error("Chrome dispatch error [%s]: %s", job.id, exc)
        await _update_job(job.id, status="failed", error=str(exc), completed_at=datetime.utcnow())
        await _update_scan(
            job.scan_id,
            chrome_job_status="failed",
            chrome_error=str(exc),
            chrome_job_completed_at=datetime.utcnow(),
        )


async def send_to_claude_in_chrome(instruction: str, scan_id: str) -> bool:
    """
    Computer-use agent loop using Anthropic API.
    Requires: pip install pyautogui pillow
    macOS: grant Accessibility + Screen Recording to Terminal.
    """
    try:
        import anthropic
        import pyautogui  # noqa
    except ImportError as exc:
        log.error("Missing dependency: %s. pip install pyautogui pillow anthropic", exc)
        return False

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set")
        return False

    client = anthropic.AsyncAnthropic(api_key=api_key)
    messages = [{"role": "user", "content": instruction}]
    deadline = datetime.utcnow() + timedelta(minutes=TIMEOUT_MINUTES)

    for turn in range(200):
        if datetime.utcnow() > deadline:
            log.warning("Computer-use agent timed out for scan %s", scan_id)
            return False
        try:
            resp = await client.beta.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                tools=[{
                    "type": "computer_20241022",
                    "name": "computer",
                    "display_width_px": 1280,
                    "display_height_px": 900,
                }],
                messages=messages,
                betas=["computer-use-2024-10-22"],
            )
        except Exception as exc:
            log.error("API error turn %d: %s", turn, exc)
            await asyncio.sleep(5)
            continue

        if resp.stop_reason == "end_turn":
            return True

        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                content = await _exec_tool(block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })

        if not tool_results:
            return True

        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})

    return False


async def _exec_tool(action: dict) -> list:
    """Execute one computer-use tool action on macOS."""
    import pyautogui
    act = action.get("action", "")
    try:
        if act == "screenshot":
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                path = f.name
            subprocess.run(["screencapture", "-x", path], check=True, timeout=10)
            with open(path, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode()
            os.unlink(path)
            return [{"type": "image", "source": {
                "type": "base64", "media_type": "image/png", "data": data,
            }}]
        elif act in ("left_click", "mouse_move", "right_click", "double_click"):
            x, y = action.get("coordinate", [640, 450])
            x, y = int(x), int(y)
            {"left_click": pyautogui.click, "mouse_move": lambda a, b: pyautogui.moveTo(a, b, duration=0.1),
             "right_click": pyautogui.rightClick, "double_click": pyautogui.doubleClick}[act](x, y)
            await asyncio.sleep(0.1)
            return [{"type": "text", "text": f"{act} ({x},{y}) ok"}]
        elif act == "type":
            pyautogui.write(action.get("text", ""), interval=0.02)
            return [{"type": "text", "text": "typed"}]
        elif act == "key":
            key = action.get("text", "")
            _map = {"Return": "enter", "BackSpace": "backspace", "Escape": "escape",
                    "Tab": "tab", "Delete": "delete"}
            k = _map.get(key, key.lower())
            if "+" in k:
                pyautogui.hotkey(*k.split("+"))
            else:
                pyautogui.press(k)
            return [{"type": "text", "text": f"key {key}"}]
        elif act == "scroll":
            x, y = action.get("coordinate", [640, 450])
            direction = action.get("direction", "down")
            amt = int(action.get("amount", 3))
            pyautogui.scroll(-amt if direction == "down" else amt, x=int(x), y=int(y))
            return [{"type": "text", "text": f"scrolled {direction}"}]
        else:
            return [{"type": "text", "text": f"unknown action: {act}"}]
    except Exception as exc:
        log.warning("Tool exec error [%s]: %s", act, exc)
        return [{"type": "text", "text": f"error: {exc}"}]


async def queue_chrome_job(
    scan_id: str,
    brand_name: str,
    domain: str,
    base_url: str,
    fallback_reason: str,
    priority: int = 1,
) -> Optional[str]:
    """Create a chrome_jobs row and update the scan. Returns job ID."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        job = ChromeJob(
            scan_id=UUID(scan_id),
            brand_name=brand_name,
            domain=domain,
            base_url=base_url,
            status="queued",
            priority=priority,
            created_at=now,
            timeout_at=now + timedelta(minutes=TIMEOUT_MINUTES),
        )
        db.add(job)
        run = await db.get(ScanRun, scan_id)
        if run:
            run.scan_mode = "chrome"
            run.chrome_job_status = "queued"
            run.chrome_job_queued_at = now
            run.scan_fallback_reason = fallback_reason
        await db.commit()
        await db.refresh(job)
        log.info("Chrome job %s queued for %s (reason=%s)", job.id, brand_name, fallback_reason)
        return str(job.id)
