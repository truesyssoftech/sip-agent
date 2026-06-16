"""
main.py
REST API entry point for SIP Saathi.

Every feature that bot.py used to handle on behalf of a Telegram user is now
exposed as an HTTP endpoint.  Callers supply a session_id (any string that
uniquely identifies a user / conversation) so that the agent remembers context
across requests — exactly like the old Telegram user_id.

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Or:
    python main.py
"""

import os
import base64
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import uvicorn

load_dotenv()

import db
import agent
from tools import get_and_clear_pending_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sip-api")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initialising database…")
    db.init_db()
    log.info("SIP Saathi API is ready.")
    yield
    log.info("SIP Saathi API shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SIP Saathi API",
    description=(
        "Stateless REST API for the SIP Saathi mutual-fund planning agent. "
        "Pass a `session_id` with every request to maintain per-user conversation context."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str = Field(
        ...,
        description="Unique identifier for the user / conversation (e.g. a UUID or username).",
        examples=["user_abc123"],
    )
    message: str = Field(
        ...,
        description="The user's message to the agent.",
        examples=["I want to save ₹50 lakh in 10 years. How much SIP do I need?"],
    )


class FileInfo(BaseModel):
    type: str          # "photo" | "document"
    filename: str      # original filename
    base64: str        # base64-encoded file contents


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    files: list[FileInfo] = []


class ResetRequest(BaseModel):
    session_id: str = Field(..., description="Session to clear.")


class ProfileResponse(BaseModel):
    session_id: str
    profile: dict | None


class HistoryEntry(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    history: list[HistoryEntry]


# ---------------------------------------------------------------------------
# Helper — encode generated files for the response
# ---------------------------------------------------------------------------

def _encode_pending_files() -> list[FileInfo]:
    """Read any files queued by the agent tools and return them base64-encoded."""
    pending = get_and_clear_pending_files()
    encoded = []
    for f in pending:
        path = Path(f["path"])
        if not path.exists():
            log.warning("Pending file not found: %s", path)
            continue
        data = base64.b64encode(path.read_bytes()).decode()
        encoded.append(FileInfo(type=f["type"], filename=path.name, base64=data))
    return encoded


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["General"])
async def root():
    """Root — confirms the API is live."""
    return {"service": "SIP Saathi", "version": "2.0.0", "docs": "/docs"}


@app.get("/health", tags=["General"])
async def health():
    """Health check for uptime monitors / load-balancers."""
    return {"status": "healthy"}


# ---- Core chat ----

@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(body: ChatRequest):
    """
    Send a message to the SIP Saathi agent and get a reply.

    - **session_id**: identifies the user; the agent remembers context across calls.
    - **message**: the user's natural-language question or request.

    The response includes the agent's text reply and any charts / PDFs
    generated during the turn, encoded as base64 strings.
    """
    log.info("chat | session=%s | msg=%r", body.session_id, body.message[:80])
    try:
        reply = await asyncio.to_thread(agent.run_turn, body.session_id, body.message)
    except Exception as e:
        log.exception("agent error for session %s", body.session_id)
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    files = _encode_pending_files()
    return ChatResponse(session_id=body.session_id, reply=reply, files=files)


# ---- Session management ----

@app.delete("/session/{session_id}", tags=["Session"])
async def reset_session(session_id: str):
    """
    Clear all conversation history and profile data for a session.
    Equivalent to the /reset command in the old Telegram bot.
    """
    db.clear_user(session_id)
    log.info("reset | session=%s", session_id)
    return {"session_id": session_id, "message": "Session cleared successfully."}


@app.get("/session/{session_id}/profile", response_model=ProfileResponse, tags=["Session"])
async def get_profile(session_id: str):
    """Return the stored profile for a session (name, risk, goals, etc.)."""
    profile = db.get_profile(session_id)
    return ProfileResponse(session_id=session_id, profile=profile)


@app.get("/session/{session_id}/history", response_model=HistoryResponse, tags=["Session"])
async def get_history(session_id: str, limit: int = 20):
    """Return the recent conversation history for a session."""
    history = db.get_recent_messages(session_id, limit=limit)
    return HistoryResponse(
        session_id=session_id,
        history=[HistoryEntry(**m) for m in history],
    )


# ---------------------------------------------------------------------------
# Direct run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
