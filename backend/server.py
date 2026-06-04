import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from agent import SECTION_ORDER, builder
from db import (
    create_conversation,
    get_conversation,
    get_messages,
    save_business_plan,
    save_message,
)

graph = None


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")

    pool = AsyncConnectionPool(
        conninfo=database_url,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    graph = builder.compile(checkpointer=checkpointer)
    yield

    await pool.close()


app = FastAPI(title="Founder Buddy API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / response models ────────────────────────────────────────────────

class StartRequest(BaseModel):
    message: str
    session_id: str | None = None

class MessageRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    session_id: str
    agent_message: str | None
    is_done: bool
    section_status: dict
    business_plan: str | None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_last_assistant_message(state) -> str | None:
    """Return the last AIMessage that is not a tool call."""
    for msg in reversed(state.values.get("messages", [])):
        if isinstance(msg, AIMessage) and not msg.tool_calls and msg.content:
            return msg.content
    return None


def get_business_plan(state) -> str | None:
    """Return the last long AIMessage (>200 chars) — the generated business plan."""
    for msg in reversed(state.values.get("messages", [])):
        if isinstance(msg, AIMessage) and not msg.tool_calls and len(msg.content) > 200:
            return msg.content
    return None


def build_response(session_id: str, state) -> ChatResponse:
    agent_message = get_last_assistant_message(state)
    is_done = state.values.get("current_section") == "done"

    return ChatResponse(
        session_id=session_id,
        agent_message=agent_message,
        is_done=is_done,
        section_status=state.values.get("section_status", {}),
        business_plan=get_business_plan(state) if is_done else None,
    )


def get_user_id(authorization: str = Header(None)) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        return decoded.get("sub")
    except Exception:
        return None


def require_graph():
    if graph is None:
        raise HTTPException(status_code=503, detail="Service is starting up, please retry.")
    return graph


# ─── POST /chat/start ─────────────────────────────────────────────────────────

@app.post("/chat/start", response_model=ChatResponse)
async def chat_start(
    req: StartRequest,
    user_id: str | None = Depends(get_user_id),
    g=Depends(require_graph),
):
    session_id = req.session_id or f"session-{uuid.uuid4().hex[:8]}"
    conversation_id = None
    if user_id is not None:
        conversation = await asyncio.to_thread(create_conversation, user_id, session_id)
        conversation_id = conversation.get("id") if conversation else None

    config = {"configurable": {"thread_id": session_id}}
    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "current_section": "problem",
        "section_status": {s: "pending" for s in SECTION_ORDER},
        "problem": "", "product": "", "features": "",
        "team_traction": "", "investment": "", "exit_strategy": "",
    }

    await g.ainvoke(initial_state, config)
    state = await g.aget_state(config)
    response = build_response(session_id, state)

    if conversation_id:
        await asyncio.to_thread(save_message, conversation_id, "user", req.message)
        if response.agent_message:
            await asyncio.to_thread(save_message, conversation_id, "assistant", response.agent_message)

    return response


# ─── POST /chat/message ───────────────────────────────────────────────────────

@app.post("/chat/message", response_model=ChatResponse)
async def chat_message(req: MessageRequest, g=Depends(require_graph)):
    config = {"configurable": {"thread_id": req.session_id}}

    state = await g.aget_state(config)
    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found. Please start a new chat.")

    await g.ainvoke({"messages": [HumanMessage(content=req.message)]}, config)
    state = await g.aget_state(config)
    response = build_response(req.session_id, state)

    conversation = await asyncio.to_thread(get_conversation, req.session_id)
    if conversation:
        conv_id = conversation["id"]
        await asyncio.to_thread(save_message, conv_id, "user", req.message)
        if response.agent_message:
            await asyncio.to_thread(save_message, conv_id, "assistant", response.agent_message)
        if response.is_done and response.business_plan:
            await asyncio.to_thread(save_business_plan, conv_id, response.business_plan)

    return response


# ─── GET /chat/state ──────────────────────────────────────────────────────────

@app.get("/chat/state", response_model=ChatResponse)
async def chat_state(session_id: str, g=Depends(require_graph)):
    config = {"configurable": {"thread_id": session_id}}
    state = await g.aget_state(config)

    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found.")

    return build_response(session_id, state)


# ─── GET /chat/messages ───────────────────────────────────────────────────────

@app.get("/chat/messages")
async def get_chat_messages(session_id: str):
    conversation = await asyncio.to_thread(get_conversation, session_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await asyncio.to_thread(get_messages, conversation["id"])
    return {"messages": messages}


# ─── DB persistence helper for streaming ─────────────────────────────────────

async def _persist_stream(session_id: str, message: str, response: ChatResponse) -> None:
    try:
        conversation = await asyncio.to_thread(get_conversation, session_id)
        if conversation:
            conv_id = conversation["id"]
            await asyncio.to_thread(save_message, conv_id, "user", message)
            if response.agent_message:
                await asyncio.to_thread(save_message, conv_id, "assistant", response.agent_message)
            if response.is_done and response.business_plan:
                await asyncio.to_thread(save_business_plan, conv_id, response.business_plan)
    except Exception:
        pass  # best-effort


# ─── POST /chat/stream (SSE) ──────────────────────────────────────────────────

@app.post("/chat/stream")
async def chat_stream(req: MessageRequest, g=Depends(require_graph)):
    config = {"configurable": {"thread_id": req.session_id}}

    state = await g.aget_state(config)
    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found. Please start a new chat.")

    async def generate():
        try:
            async for event in g.astream_events(
                {"messages": [HumanMessage(content=req.message)]},
                config,
                version="v2",
            ):
                # Forward tokens only from the assistant node. Tool-call
                # responses have empty content so they are filtered out by
                # the `chunk.content` check.
                if (
                    event["event"] == "on_chat_model_stream"
                    and event.get("metadata", {}).get("langgraph_node") == "assistant"
                ):
                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Generation failed. Please try again.'})}\n\n"
            return

        final_state = await g.aget_state(config)
        response = build_response(req.session_id, final_state)
        yield f"data: {json.dumps({'type': 'done', **response.model_dump()})}\n\n"

        asyncio.ensure_future(_persist_stream(req.session_id, req.message, response))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
