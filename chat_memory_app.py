"""Standalone FastAPI service adding per-session chat history/memory on top
of the existing Turn2Law RAG system.

Runs independently of app.py on its own port. Reuses main.ragu() for
answer generation without modifying or duplicating it. Existing files
(app.py, main.py, etc.) are never touched by this module.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Load the same .env used by main.py / app.py (GROQ_API_KEY, PINECONE_API_KEY, etc.)
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)
load_dotenv()

# Reuse the existing RAG pipeline as-is.
from main import ragu, groq_model_name

import chat_memory_db as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== CONFIG =====
# Number of most recent prior turns (user + assistant messages combined)
# included as context when answering a follow-up question.
HISTORY_WINDOW_MESSAGES = 6

db.init_db()

app = FastAPI(
    title="Turn2Law Chat Memory API",
    version="1.0.0",
    description="Adds per-session conversation history on top of the existing RAG system.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Identifier for the conversation/session")
    query: str = Field(..., min_length=1, max_length=1000, description="The user's question")


class ChatResponse(BaseModel):
    response: str
    model_used: str
    session_id: str


class MemorySettingRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="Identifier for the user/session")
    enabled: bool = Field(..., description="Whether conversation history should be used in /api/chat")


class MemorySettingResponse(BaseModel):
    user_id: str
    memory_enabled: bool


def build_context_prompt(history: list[dict], query: str) -> str:
    """Prefix the new question with recent conversation history, if any."""
    if not history:
        return query

    lines = ["Previous conversation:"]
    for msg in history:
        speaker = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {msg['content']}")
    lines.append("")
    lines.append(f"New question: {query}")
    return "\n".join(lines)


@app.get("/")
async def root():
    return {"message": "Turn2Law Chat Memory API is running", "status": "healthy"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Answer a query using recent session history as context (if the memory
    toggle is ON for this session_id), then persist the exchange regardless.
    If answer generation fails, nothing is saved."""
    if db.is_memory_enabled(request.session_id):
        history = db.get_history(request.session_id, limit=HISTORY_WINDOW_MESSAGES)
    else:
        history = []
    prompt = build_context_prompt(history, request.query)

    logger.info(f"[{request.session_id}] New chat query: {request.query[:100]}...")

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, ragu, prompt)
    except Exception as e:
        logger.error(f"[{request.session_id}] ragu() failed, not saving to history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing query: {str(e)}",
        )

    # Only persist once we have a successful answer, so failures never pollute history.
    db.add_message(request.session_id, "user", request.query)
    db.add_message(request.session_id, "assistant", response)

    return ChatResponse(
        response=response,
        model_used=groq_model_name,
        session_id=request.session_id,
    )


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """Return the full saved conversation for a session."""
    history = db.get_history(session_id)
    return {"session_id": session_id, "history": history}


@app.delete("/api/history/{session_id}")
async def delete_history(session_id: str):
    """Clear a session's saved conversation history."""
    deleted_count = db.clear_history(session_id)
    return {"session_id": session_id, "deleted_messages": deleted_count}


@app.post("/api/memory-setting", response_model=MemorySettingResponse)
async def set_memory_setting(request: MemorySettingRequest):
    """Turn conversation-history usage on/off for a user. Messages are still
    saved to history either way; this only controls whether /api/chat reads
    history back into the prompt."""
    db.set_memory_enabled(request.user_id, request.enabled)
    return MemorySettingResponse(user_id=request.user_id, memory_enabled=request.enabled)


@app.get("/api/memory-setting/{user_id}", response_model=MemorySettingResponse)
async def get_memory_setting(user_id: str):
    """Get the current memory toggle for a user. Defaults to True (ON) if never set."""
    enabled = db.is_memory_enabled(user_id)
    return MemorySettingResponse(user_id=user_id, memory_enabled=enabled)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
