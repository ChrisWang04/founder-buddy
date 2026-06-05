# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Founder Buddy** — an AI startup advisor that walks founders through a structured Q&A and generates an investor-ready business plan. Split into `backend/` (FastAPI + LangGraph) and `frontend/` (Next.js + Supabase auth).

---

## Backend (`backend/`)

### Commands

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt

uvicorn server:app --reload --port 8080   # Dev server
python agent.py                            # Run agent as CLI loop (MemorySaver, no DB needed)
fly deploy                                 # Deploy to Fly.io (run from backend/)
fly logs --app founder-buddy-backend       # Tail prod logs
fly secrets set KEY=value                  # Set a prod env var
```

### Testing

```bash
pip install -r requirements-dev.txt

pytest tests/                         # Full suite + coverage (85% gate, ~2s, 88 tests)
pytest tests/unit/ --no-cov           # Unit tests only (no coverage gate)
pytest tests/integration/ --no-cov    # Integration tests only
pytest -k "test_name" --no-cov        # Single test by name
pytest -x -v -s --no-cov             # Stop-on-fail, verbose, show prints
```

Always pass `--no-cov` when running a subset — the 85% gate fails on incomplete collection by design.

### Architecture

The backend is a thin FastAPI layer over a **LangGraph agent**. The graph is the product.

**`agent.py` — the graph (agent-driven ReAct pattern)**

`FounderBuddyState` holds: `messages` (with `add_messages` reducer), `current_section`, `section_status` (dict), and six text fields (`problem`, `product`, `features`, `team_traction`, `investment`, `exit_strategy`).

Two tools:
- `complete_section(content)` — signals that the current section is done and provides the summary
- `modify_section(section)` — signals that a previously completed section needs re-collection

Two nodes, looping via `tools_condition`:
- `assistant_node` (async): if `current_section == "done"`, calls plain `llm` to generate the business plan; otherwise calls `llm_with_tools` with the section-specific prompt from `SECTION_PROMPTS`. Returns `{"messages": [response]}`.
- `tools_node` (sync): executes tool calls. For `complete_section`: saves content to state, marks section done, advances `current_section` to the next (or `"done"` if last). For `modify_section`: clears the target section's content and sets `current_section` to it.

Graph edges: `START → assistant → (tools_condition) → tools → assistant` (loop) or `END`.

**No `interrupt()`**. Every HTTP request invokes the graph to `END`. The next request injects a `HumanMessage` via the `add_messages` reducer, which appends it to the checkpoint state before the graph runs again.

**`server.py` — the HTTP layer**

- `graph = None` at module level; compiled inside `lifespan` with `AsyncPostgresSaver` backed by `AsyncConnectionPool` (psycopg3).
- `POST /chat/start` — creates session, invokes with `initial_state` (first section marked `in_progress`).
- `POST /chat/message` — injects `HumanMessage`, invokes graph, returns JSON.
- `POST /chat/stream` — injects `HumanMessage`, streams via `astream_events(version="v2")`, filters `on_chat_model_stream` events from `langgraph_node == "assistant"`, skipping tool-call chunks (only emits text blocks). After streaming, fetches final state and emits a `{"type": "done", ...ChatResponse}` event.
- `build_response()` uses `get_last_assistant_message()` (scans reversed messages for last non-tool-call `AIMessage`) and `get_business_plan()` (last AIMessage with >200 chars, only when `is_done`).
- `_extract_text(content)` normalizes Anthropic's content — can be a plain string or a list of `{"type": "text", "text": "..."}` blocks.

**`db.py`** — synchronous Supabase client. All calls in async handlers are wrapped in `asyncio.to_thread()`.

### Required env vars (`backend/.env`)

```
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_SECRET_KEY=
DATABASE_URL=            # postgresql:// — must use Supabase pooler URL (not direct) for Fly.io
LANGSMITH_API_KEY=       # optional
LANGSMITH_TRACING=true   # optional
```

`DATABASE_URL` must use the **pooler** URL (`aws-0-region.pooler.supabase.com:5432`, Session mode) — the direct connection (`db.xxx.supabase.co`) is not resolvable from Fly.io's network.

### Deployment

Fly.io app `founder-buddy-backend`, region `yyz`. Production URL hardcoded in `frontend/app/components/FounderBuddyApp.tsx` as `API_BASE_URL`.

---

## Frontend (`frontend/`)

### Commands

```bash
cd frontend
npm install
npm run dev          # localhost:3000
npm run build
vercel --prod        # Deploy to Vercel (permanent alias: founder-buddy-frontend.vercel.app)
```

The git repo is **not** connected to Vercel via GitHub — deploys always go through the CLI. The permanent production URL is `https://founder-buddy-frontend.vercel.app`.

### Testing

```bash
npm test              # Vitest watch mode (~29 tests)
npm run test:coverage # Run once with coverage report
```

Tests live in `frontend/__tests__/`. Covered: `lib/sse.ts` (SSE parser), `lib/conversationLabel.ts` (label logic), component rendering.

### Architecture

**Next.js 16** App Router, Tailwind, Supabase auth.

**`FounderBuddyApp.tsx`** owns all state and API calls:
- `sessionId`, `messages`, `progress` (section statuses), `businessPlan`, `streamingMessage`, `isLoading`, `convListKey`.
- **First message** → `POST /chat/start` (JSON response, no streaming).
- **Subsequent messages** → `POST /chat/stream` (SSE). Token events accumulate into `streamingMessage` (shown as a live streaming chat bubble via `ChatInterface`). On `done`: `streamingMessage` is cleared, `agent_message` is added to `messages`, and `businessPlan` is set if `is_done && business_plan`.
- The `BusinessPlanDisplay` panel only renders when `businessPlan` is set — never during Q&A.
- `convListKey` bumps on first message (to show new conv in sidebar) and when `businessPlan` is set (to update the title).

**`ConversationList.tsx`** queries Supabase directly (client-side) with `select("*, business_plans(content), messages(content, role)")`. The conversation label uses the BP content if available, falling back to the first user message (`lib/conversationLabel.ts`).

**`handleLoadConversation`**: loads message history from `GET /chat/messages` and graph state from `GET /chat/state`. If `/chat/state` returns 404 (session has no PostgreSQL checkpoint — pre-migration sessions), it clears `sessionId` and shows a notice so the user can't send into a dead session.

**`lib/sse.ts`** — pure SSE frame parser. Splits on `\n\n`, parses `data: {...}` JSON. Used by `FounderBuddyApp` with a `TextDecoder({stream: true})` loop.

### Required env vars (`frontend/.env.local`)

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
```

---

## Cross-cutting design decisions

- **Session identity**: `session_id` = LangGraph `thread_id` = Supabase `conversations.session_id`. Same string everywhere.
- **No interrupt()**: the graph runs to END on every request. Subsequent requests append `HumanMessage` to the checkpoint via `add_messages`. This means `/chat/stream` sends `{"messages": [HumanMessage(...)]}`, not `Command(resume=...)`.
- **Section status**: starts with `problem: "in_progress"`, others `pending`. `tools_node` marks each section `done` and the next `in_progress` when `complete_section` fires.
- **Streaming filter**: SSE only forwards text-type content blocks from the `assistant` node. Tool-call chunks (`{"type": "tool_use", ...}`) are explicitly skipped to prevent garbage from reaching the frontend.
- **Content normalization**: `_extract_text()` handles both `str` and `list[{"type":"text","text":"..."}]` — Anthropic's API returns a list when invoked via `astream_events`.
- **No checkpoint TTL**: `AsyncPostgresSaver` rows grow forever. No expiry configured.
