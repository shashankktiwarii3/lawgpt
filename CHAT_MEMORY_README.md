# Chat Memory Service

An add-on FastAPI service that gives the existing Turn2Law RAG system
per-session conversation history, so follow-up questions get answered with
context from earlier turns in the same conversation.

It is completely separate from the original API:

- `app.py` — the original API, unchanged, still runs on port **8001**.
- `chat_memory_app.py` — this new service, runs on its own port **8002**.

They do not depend on each other and can run at the same time. This service
imports `main.ragu()` directly to generate answers (no logic is duplicated),
and adds a new SQLite file, `chat_memory.db`, for storing history. No new
external service or API key is needed.

## How it works

1. `POST /api/chat` receives `{session_id, query}`.
2. It loads the last `HISTORY_WINDOW_MESSAGES` turns (constant defined at the
   top of `chat_memory_app.py`) for that `session_id` from `chat_memory.db`.
3. It prepends that history to the new question and calls `main.ragu()` with
   the combined prompt.
4. Only if `ragu()` succeeds are the question and answer saved to history —
   a failed/errored answer is never persisted, so history doesn't get
   polluted with broken replies.

## Running it

Use the same virtual environment and `.env` file as the main app (it needs
`GROQ_API_KEY` and `PINECONE_API_KEY` because it imports `main.py`):

```bash
python chat_memory_app.py
```

This starts the service at `http://localhost:8002`. `chat_memory.db` is
created automatically in the project root on first run.

## Endpoints

### `POST /api/chat`

Request:
```json
{ "session_id": "user-123", "query": "What is the punishment for theft?" }
```

Response:
```json
{
  "response": "According to Section 378 of the IPC...",
  "model_used": "llama-3.3-70b-versatile",
  "session_id": "user-123"
}
```

Example:
```bash
curl -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "user-123", "query": "What is the punishment for theft?"}'
```

### `GET /api/history/{session_id}`

Returns the full saved conversation for a session, in order.

```bash
curl http://localhost:8002/api/history/user-123
```

### `DELETE /api/history/{session_id}`

Clears a session's saved history.

```bash
curl -X DELETE http://localhost:8002/api/history/user-123
```

## Notes

- `HISTORY_WINDOW_MESSAGES` in `chat_memory_app.py` controls how many recent
  messages are used as context per question — change that constant to tune
  it.
- `chat_memory.db` is a new local file created at runtime; consider adding
  it to `.gitignore` if you don't want it tracked by git.
