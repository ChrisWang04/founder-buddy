import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SECRET_KEY"),
)


def create_conversation(user_id: str, session_id: str) -> dict:
    """创建新对话记录"""
    result = supabase.table("conversations").insert({
        "user_id": user_id,
        "session_id": session_id,
    }).execute()
    return result.data[0] if result.data else None


def get_conversation(session_id: str) -> dict:
    """根据 session_id 查找对话"""
    result = supabase.table("conversations").select("*").eq("session_id", session_id).execute()
    return result.data[0] if result.data else None


def save_business_plan(conversation_id: int, content: str) -> dict:
    """保存或更新 BP"""
    # 先检查是否已有 BP
    existing = supabase.table("business_plans").select("*").eq("conversation_id", conversation_id).execute()

    if existing.data:
        # 更新
        result = supabase.table("business_plans").update({
            "content": content,
            "updated_at": "now()",
        }).eq("conversation_id", conversation_id).execute()
    else:
        # 新建
        result = supabase.table("business_plans").insert({
            "conversation_id": conversation_id,
            "content": content,
        }).execute()

    return result.data[0] if result.data else None


def get_business_plan(conversation_id: int) -> dict:
    """获取 BP"""
    result = supabase.table("business_plans").select("*").eq("conversation_id", conversation_id).execute()
    return result.data[0] if result.data else None


def get_user_conversations(user_id: str) -> list:
    """获取用户所有对话"""
    result = supabase.table("conversations").select("*, business_plans(content)").eq("user_id", user_id).order("created_at", desc=True).execute()
    return result.data or []

def save_message(conversation_id: int, role: str, content: str) -> dict:
    """存单条消息"""
    result = supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
    }).execute()
    return result.data[0] if result.data else None


def get_messages(conversation_id: int) -> list:
    """获取对话的所有消息"""
    result = supabase.table("messages").select("*").eq(
        "conversation_id", conversation_id
    ).order("created_at").execute()
    return result.data or []