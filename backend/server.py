import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from agent import builder
from db import (
    create_conversation,
    get_conversation,
    get_messages,
    save_business_plan,
    save_message,
)

graph = None


# ─── 生命周期：启动时建连接池和 checkpointer ────────────────
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

# ─── CORS（允许前端访问）───────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 开发阶段先全开，上线再收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 请求/响应结构 ─────────────────────────────────────────
class StartRequest(BaseModel):
    message: str                      # 用户第一句话
    session_id: str | None = None     # 可选，不传就自动生成

class MessageRequest(BaseModel):
    session_id: str                   # 必须传，对应哪个对话
    message: str                      # 用户回答

class ChatResponse(BaseModel):
    session_id: str
    agent_message: str | None         # agent 下一句话（None = 对话结束）
    is_done: bool                     # True = 已生成完整 BP
    section_status: dict              # 进度条状态
    business_plan: str | None         # 仅在 is_done=True 时有值


# ─── 辅助函数：读取最新 interrupt ──────────────────────────
def get_interrupt_message(state) -> str | None:
    if state.tasks and state.tasks[0].interrupts:
        return state.tasks[0].interrupts[-1].value
    return None

def get_business_plan(state) -> str | None:
    messages = state.values.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.__class__.__name__ == "AIMessage":
            if len(msg.content) > 200:
                return msg.content
    return None

def build_response(session_id: str, state) -> ChatResponse:
    interrupt_msg = get_interrupt_message(state)
    plan_ready_for_edit = state.values.get("current_section") == "done" and interrupt_msg is not None
    is_done = interrupt_msg is None or plan_ready_for_edit

    return ChatResponse(
        session_id=session_id,
        agent_message=interrupt_msg,
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


# ─── POST /chat/start ─────────────────────────────────────
@app.post("/chat/start", response_model=ChatResponse)
async def chat_start(req: StartRequest, user_id: str | None = Depends(get_user_id), g=Depends(require_graph)):
    session_id = req.session_id or f"session-{uuid.uuid4().hex[:8]}"
    conversation_id = None
    if user_id is not None:
        conversation = await asyncio.to_thread(create_conversation, user_id, session_id)
        conversation_id = conversation.get("id") if conversation else None

    config = {"configurable": {"thread_id": session_id}}
    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "current_section": "welcome",
        "current_question_index": 0,
        "welcome_done": False,
        "welcome_question_count": 0,
        "edit_in_progress": False,
        "section_status": {},
        "problem": "",
        "product": "",
        "features": "",
        "team_traction": "",
        "investment": "",
        "exit_strategy": "",
    }

    await g.ainvoke(initial_state, config)
    state = await g.aget_state(config)
    response = build_response(session_id, state)

    if conversation_id:
        await asyncio.to_thread(save_message, conversation_id, "user", req.message)
        if response.agent_message:
            await asyncio.to_thread(save_message, conversation_id, "assistant", response.agent_message)

    return response


# ─── POST /chat/message ───────────────────────────────────
@app.post("/chat/message", response_model=ChatResponse)
async def chat_message(req: MessageRequest, g=Depends(require_graph)):
    config = {"configurable": {"thread_id": req.session_id}}

    state = await g.aget_state(config)
    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found. Please start a new chat.")

    await g.ainvoke(Command(resume=req.message), config)
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


# ─── GET /chat/state ──────────────────────────────────────
@app.get("/chat/state", response_model=ChatResponse)
async def chat_state(session_id: str, g=Depends(require_graph)):
    config = {"configurable": {"thread_id": session_id}}
    state = await g.aget_state(config)

    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found.")

    return build_response(session_id, state)


# ─── GET /chat/messages ───────────────────────────────────
@app.get("/chat/messages")
async def get_chat_messages(session_id: str):
    conversation = await asyncio.to_thread(get_conversation, session_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await asyncio.to_thread(get_messages, conversation["id"])
    return {"messages": messages}


# ─── DB persistence helper for streaming endpoint ─────────
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
        pass  # persistence is best-effort; don't crash the stream


# ─── POST /chat/stream (SSE) ──────────────────────────────
@app.post("/chat/stream")
async def chat_stream(req: MessageRequest, g=Depends(require_graph)):
    config = {"configurable": {"thread_id": req.session_id}}

    state = await g.aget_state(config)
    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found. Please start a new chat.")

    async def generate():
        # Phase 1: stream LLM tokens; surface errors to client immediately
        try:
            async for event in g.astream_events(
                Command(resume=req.message), config, version="v2"
            ):
                if (
                    event["event"] == "on_chat_model_stream"
                    and event.get("metadata", {}).get("langgraph_node") == "generate_bp"
                ):
                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Generation failed. Please try again.'})}\n\n"
            return

        # Phase 2: build and send done event so client can proceed immediately
        final_state = await g.aget_state(config)
        response = build_response(req.session_id, final_state)
        yield f"data: {json.dumps({'type': 'done', **response.model_dump()})}\n\n"

        # Phase 3: persist to DB as a fire-and-forget task so a client
        # disconnect after phase 2 cannot prevent messages from being saved
        asyncio.ensure_future(_persist_stream(req.session_id, req.message, response))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── 健康检查 ─────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}
