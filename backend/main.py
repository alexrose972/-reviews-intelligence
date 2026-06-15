"""Reviews Intelligence — FastAPI app."""

import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import (
    BackgroundTasks, Depends, FastAPI, HTTPException,
    Request, Response, WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import desc, select
from starlette.middleware.sessions import SessionMiddleware

from .auth import get_google_auth_url, handle_oauth_callback, require_auth
from .database import AsyncSessionLocal, ScanRun, User, init_db
from .scanner.engine import run_scan
from .sf_client import search_sf_accounts

log = logging.getLogger("main")

app = FastAPI(title="Reviews Intelligence", docs_url=None, redoc_url=None)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", secrets.token_urlsafe(32)),
    session_cookie="ri_session",
    https_only=bool(os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("NODE_ENV") == "production"),
    same_site="lax",
    max_age=8 * 60 * 60,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket connection manager ──────────────────────────────────────────────

class WSManager:
    def __init__(self):
        self._connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, scan_id: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(scan_id, []).append(ws)

    def disconnect(self, scan_id: str, ws: WebSocket):
        conns = self._connections.get(scan_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, scan_id: str, message: dict):
        for ws in list(self._connections.get(scan_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(scan_id, ws)

ws_manager = WSManager()


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await init_db()
    log.info("DB initialized.")


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login(request: Request):
    url = get_google_auth_url(request)
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"/login?error={error}")
    if not code:
        return RedirectResponse("/login?error=no_code")
    try:
        async with AsyncSessionLocal() as db:
            user = await handle_oauth_callback(code, state, request, db)
        request.session["user"] = {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "photo": user.profile_photo,
        }
        return RedirectResponse("/")
    except HTTPException as e:
        if e.status_code == 403:
            return RedirectResponse("/login?error=domain")
        return RedirectResponse(f"/login?error=oauth")


@app.post("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── API routes ─────────────────────────────────────────────────────────────────

@app.get("/api/me")
async def api_me(user: dict = Depends(require_auth)):
    return user


@app.get("/api/sf-accounts")
async def api_sf_accounts(q: str = "", user: dict = Depends(require_auth)):
    return search_sf_accounts(q)


@app.get("/api/scans")
async def api_list_scans(limit: int = 20, user: dict = Depends(require_auth)):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScanRun).order_by(desc(ScanRun.triggered_at)).limit(limit)
        )
        runs = result.scalars().all()
    return [_serialize_run(r) for r in runs]


class ScanRequest(BaseModel):
    domain: str
    brand_name: str
    account_owner: Optional[str] = "Unknown"
    sf_reviews_provider: Optional[str] = None
    sf_loyalty_provider: Optional[str] = None


@app.post("/api/scans")
async def api_create_scan(
    body: ScanRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth),
):
    scan_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        run = ScanRun(
            id=scan_id,
            brand_name=body.brand_name,
            domain=body.domain,
            triggered_by=user["email"],
            status="pending",
            sf_platform=body.sf_reviews_provider,
        )
        db.add(run)
        await db.commit()

    async def _run():
        await run_scan(
            scan_id=scan_id,
            brand_name=body.brand_name,
            domain=body.domain,
            account_owner=body.account_owner or user["name"],
            sf_reviews_provider=body.sf_reviews_provider,
            triggered_by=user["email"],
            broadcast=ws_manager.broadcast,
        )

    background_tasks.add_task(_run)
    return {"scan_id": scan_id}


@app.get("/api/scans/{scan_id}")
async def api_get_scan(scan_id: str, user: dict = Depends(require_auth)):
    async with AsyncSessionLocal() as db:
        run = await db.get(ScanRun, scan_id)
    if not run:
        raise HTTPException(404, "Scan not found")
    return _serialize_run(run)


@app.get("/api/scans/{scan_id}/pdf")
async def api_download_pdf(scan_id: str, user: dict = Depends(require_auth)):
    async with AsyncSessionLocal() as db:
        run = await db.get(ScanRun, scan_id)
    if not run or not run.pdf_path:
        raise HTTPException(404, "PDF not found")
    path = Path(run.pdf_path)
    if not path.exists():
        raise HTTPException(404, "PDF file not found on disk")
    media = "application/pdf" if str(path).endswith(".pdf") else "text/html"
    return FileResponse(str(path), media_type=media,
                        filename=f"{run.brand_name.replace(' ', '_')}_brief{path.suffix}")


@app.get("/api/scans/{scan_id}/screenshot/{label}")
async def api_screenshot(scan_id: str, label: str, user: dict = Depends(require_auth)):
    shot_path = Path("/screenshots") / scan_id / f"{label}.png"
    if not shot_path.exists():
        raise HTTPException(404, "Screenshot not found")
    return FileResponse(str(shot_path), media_type="image/png")


@app.get("/api/check-recent")
async def api_check_recent(domain: str, user: dict = Depends(require_auth)):
    cutoff = datetime.utcnow() - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScanRun)
            .where(ScanRun.domain == domain, ScanRun.triggered_at >= cutoff,
                   ScanRun.status == "complete")
            .order_by(desc(ScanRun.triggered_at))
            .limit(1)
        )
        run = result.scalar_one_or_none()
    if run:
        return {"found": True, "scan": _serialize_run(run)}
    return {"found": False}


@app.get("/api/scans/{scan_id}/export")
async def api_export_scan(scan_id: str, user: dict = Depends(require_auth)):
    """Export single scan as Excel."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    async with AsyncSessionLocal() as db:
        run = await db.get(ScanRun, scan_id)
    if not run:
        raise HTTPException(404, "Scan not found")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Scan Results"
    _write_scan_to_sheet(ws, run)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="scan_{scan_id[:8]}.xlsx"'},
    )


@app.get("/api/history/export")
async def api_export_history(user: dict = Depends(require_auth)):
    """Export all completed scans as Excel (4-sheet format)."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from .scanner.utils import SCORE_WEIGHTS, DIMENSION_LABELS

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScanRun).where(ScanRun.status == "complete")
            .order_by(desc(ScanRun.triggered_at))
        )
        runs = result.scalars().all()

    PURPLE = PatternFill("solid", fgColor="3C1053")
    WHITE_BOLD = Font(color="FFFFFF", bold=True, size=9)

    wb = openpyxl.Workbook()
    dim_keys = list(SCORE_WEIGHTS.keys())

    # Sheet 1: Summary
    ws1 = wb.active
    ws1.title = "Summary"
    headers = (["Brand", "Domain", "AE", "Score", "Grade", "Detected Platform",
                "SF Platform", "Mismatch", "Vertical", "Date", "Run By"]
               + [DIMENSION_LABELS[k] for k in dim_keys])
    for col, h in enumerate(headers, 1):
        c = ws1.cell(row=1, column=col, value=h)
        c.fill = PURPLE; c.font = WHITE_BOLD
    for r_idx, run in enumerate(runs, 2):
        scores = run.scores_json or {}
        row = [
            run.brand_name, run.domain, "", run.overall_score, run.grade,
            run.detected_platform or "", run.sf_platform or "",
            "YES" if run.platform_mismatch else "",
            (run.signals_json or {}).get("vertical", "") if run.signals_json else "",
            run.triggered_at.strftime("%Y-%m-%d") if run.triggered_at else "",
            run.triggered_by,
        ] + [scores.get(k, {}).get("score", 0) for k in dim_keys]
        for col, val in enumerate(row, 1):
            ws1.cell(row=r_idx, column=col, value=val)

    # Sheet 2: Pitch Angles
    ws2 = wb.create_sheet("Pitch Angles")
    for col, h in enumerate(["Brand", "Score", "Pitch 1", "Pitch 2", "Pitch 3"], 1):
        c = ws2.cell(row=1, column=col, value=h)
        c.fill = PURPLE; c.font = WHITE_BOLD
    sorted_runs = sorted(runs, key=lambda r: r.overall_score or 0)
    for r_idx, run in enumerate(sorted_runs, 2):
        pitches = (run.pitch_angles_json or []) + ["", "", ""]
        for col, val in enumerate([run.brand_name, run.overall_score] + pitches[:3], 1):
            c = ws2.cell(row=r_idx, column=col, value=val)
            if col >= 3:
                c.alignment = Alignment(wrap_text=True, vertical="top")

    # Sheet 3: Recommendations
    ws3 = wb.create_sheet("Recommendations")
    for col, h in enumerate(["Brand", "Score", "Fix 1", "Fix 2", "Fix 3"], 1):
        c = ws3.cell(row=1, column=col, value=h)
        c.fill = PURPLE; c.font = WHITE_BOLD
    for r_idx, run in enumerate(sorted_runs, 2):
        recs = (run.recommendations_json or []) + ["", "", ""]
        for col, val in enumerate([run.brand_name, run.overall_score] + recs[:3], 1):
            c = ws3.cell(row=r_idx, column=col, value=val)
            if col >= 3:
                c.alignment = Alignment(wrap_text=True, vertical="top")

    # Sheet 4: LLM Probe
    ws4 = wb.create_sheet("LLM Probe Results")
    for col, h in enumerate(["Brand", "LLM Score", "Review Quote", "Complaint", "Failed?"], 1):
        c = ws4.cell(row=1, column=col, value=h)
        c.fill = PURPLE; c.font = WHITE_BOLD
    for r_idx, run in enumerate(runs, 2):
        llm = run.llm_probe_json or {}
        scores = run.scores_json or {}
        for col, val in enumerate([
            run.brand_name,
            scores.get("llm_crawlability", {}).get("score", 0),
            llm.get("review_quote", ""),
            llm.get("complaint_quote", ""),
            "YES" if llm.get("failed") else "",
        ], 1):
            c = ws4.cell(row=r_idx, column=col, value=val)
            if col in (3, 4):
                c.alignment = Alignment(wrap_text=True, vertical="top")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="reviews_intelligence_report.xlsx"'},
    )


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/scans/{scan_id}")
async def ws_scan(scan_id: str, ws: WebSocket):
    await ws_manager.connect(scan_id, ws)
    try:
        # If scan already complete, send current state immediately
        async with AsyncSessionLocal() as db:
            run = await db.get(ScanRun, scan_id)
        if run and run.status in ("complete", "failed"):
            await ws.send_json({"type": "status", "status": run.status, "result": _serialize_run(run)})
        # Keep connection alive until client disconnects
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(scan_id, ws)
    except Exception:
        ws_manager.disconnect(scan_id, ws)


# ── Frontend (serve React build) ──────────────────────────────────────────────

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        # Don't intercept API/auth/ws routes
        if full_path.startswith(("api/", "auth/", "ws/", "health")):
            raise HTTPException(404)
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text())
        return HTMLResponse("<h1>Frontend not built. Run: cd frontend && npm run build</h1>")
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return HTMLResponse(
            "<h1>Reviews Intelligence API</h1>"
            "<p>Frontend not built. Run: <code>cd frontend && npm run build</code></p>"
            "<p><a href='/docs'>API docs</a></p>"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_run(run: ScanRun) -> dict:
    return {
        "id": str(run.id),
        "brand_name": run.brand_name,
        "domain": run.domain,
        "triggered_by": run.triggered_by,
        "triggered_at": run.triggered_at.isoformat() if run.triggered_at else None,
        "status": run.status,
        "overall_score": run.overall_score,
        "grade": run.grade,
        "scores": run.scores_json,
        "recommendations": run.recommendations_json,
        "pitch_angles": run.pitch_angles_json,
        "llm_probe": run.llm_probe_json,
        "detected_platform": run.detected_platform,
        "sf_platform": run.sf_platform,
        "platform_mismatch": run.platform_mismatch,
        "pdf_path": run.pdf_path,
        "slinger_drafts": run.slinger_drafts_json,
        "screenshots": run.screenshots_json,
        "error_message": run.error_message,
    }


def _write_scan_to_sheet(ws, run: ScanRun):
    from .scanner.utils import DIMENSION_LABELS, SCORE_WEIGHTS
    ws.append(["Brand", run.brand_name])
    ws.append(["Domain", run.domain])
    ws.append(["Score", run.overall_score])
    ws.append(["Grade", run.grade])
    ws.append(["Platform", run.detected_platform or ""])
    ws.append([])
    ws.append(["Dimension", "Score", "Max", "Finding"])
    scores = run.scores_json or {}
    for key in SCORE_WEIGHTS:
        dim = scores.get(key, {})
        ws.append([
            DIMENSION_LABELS.get(key, key),
            dim.get("score", 0),
            dim.get("max_score", SCORE_WEIGHTS[key]),
            dim.get("finding", ""),
        ])
