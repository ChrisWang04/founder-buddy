from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command
import jwt
import time
import uuid

from agent import graph
from db import create_conversation, get_conversation, save_business_plan

app = FastAPI(title="Founder Buddy API")

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
    """从 graph state 里拿最新的 interrupt 内容"""
    if state.tasks and state.tasks[0].interrupts:
        return state.tasks[0].interrupts[-1].value
    return None

def get_business_plan(state) -> str | None:
    """对话结束后，从 messages 里取最后一条 AI 消息（BP 内容）"""
    messages = state.values.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.__class__.__name__ == "AIMessage":
            # 只返回长的那条（BP），不返回短的提示
            if len(msg.content) > 200:
                return msg.content
    return None

def build_response(session_id: str, state) -> ChatResponse:
    """统一把 graph state 转成 API response"""
    interrupt_msg = get_interrupt_message(state)
    plan_ready_for_edit = state.values.get("current_section") == "done" and interrupt_msg is not None
    is_done = interrupt_msg is None or plan_ready_for_edit  # 没有 interrupt = 图跑完了

    section_status = state.values.get("section_status", {})

    return ChatResponse(
        session_id=session_id,
        agent_message=interrupt_msg,
        is_done=is_done,
        section_status=section_status,
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


# ─── POST /chat/start ─────────────────────────────────────
@app.post("/chat/start", response_model=ChatResponse)
def chat_start(req: StartRequest, user_id: str | None = Depends(get_user_id)):
    """开始一个新对话"""
    session_id = req.session_id or f"session-{uuid.uuid4().hex[:8]}"
    conversation_id = None
    if user_id is not None:
        conversation = create_conversation(user_id, session_id)
        conversation_id = conversation.get("id") if conversation else None
    config = {"configurable": {"thread_id": session_id}}

    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "current_section": "welcome",
        "current_question_index": 0,
        "welcome_done": False,
        "welcome_question_count": 0,
        "section_status": {},
        "problem": "",
        "product": "",
        "features": "",
        "team_traction": "",
        "investment": "",
        "exit_strategy": "",
    }

    graph.invoke(initial_state, config)
    state = graph.get_state(config)
    return build_response(session_id, state)


# ─── POST /chat/message ───────────────────────────────────
@app.post("/chat/message", response_model=ChatResponse)
def chat_message(req: MessageRequest):
    """继续已有对话，传入用户回答"""
    config = {"configurable": {"thread_id": req.session_id}}

    # 检查 session 是否存在
    state = graph.get_state(config)
    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found. Please start a new chat.")

    graph.invoke(Command(resume=req.message), config)
    state = graph.get_state(config)
    response = build_response(req.session_id, state)

    if response.is_done and response.business_plan is not None:
        conversation = get_conversation(req.session_id)
        if conversation:
            save_business_plan(conversation["id"], response.business_plan)

    return response


# ─── GET /chat/state ──────────────────────────────────────
@app.get("/chat/state", response_model=ChatResponse)
def chat_state(session_id: str):
    """读取当前进度（给进度条用）"""
    config = {"configurable": {"thread_id": session_id}}
    state = graph.get_state(config)

    if state.values == {}:
        raise HTTPException(status_code=404, detail="Session not found.")

    return build_response(session_id, state)


# ─── 健康检查 ─────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}
