from dotenv import load_dotenv
import json
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()

# ─── State 定义 ───────────────────────────────────────────
class FounderBuddyState(TypedDict):
    messages: Annotated[list, add_messages]
    current_section: str
    current_question_index: int
    section_status: dict
    problem: str
    product: str
    features: str
    team_traction: str
    investment: str
    exit_strategy: str
    welcome_done: bool
    welcome_question_count: int
    edit_in_progress: bool

# ─── 问题库 ───────────────────────────────────────────────
QUESTIONS = {
    "problem": [
        "What problem are you trying to solve?",
    ],
    "product": [
        "What is your product or service, in simple terms?",
        "How does it solve the problem you just described?",
    ],
    "features": [
        "What are the main things your product can do? List up to 5.",
        "What's the one thing about your product that you're most proud of?",
    ],
    "team_traction": [
        "Who is on your team and what are their roles?",
        "Do you have any early users or revenue so far?",
    ],
    "investment": [
        "How much funding are you looking to raise?",
        "What will you use the funding for?",
    ],
    "exit_strategy": [
        "One day, how do you see this business ending — selling it, going public, or just keeping it?",
        "Is there a big company in your space that might want to buy you someday?",
    ],
}

SECTION_ORDER = ["problem", "product", "features", "team_traction", "investment", "exit_strategy"]

SECTION_LABELS = {
    "problem": "Problem",
    "product": "Product",
    "features": "Features",
    "team_traction": "Team & Traction",
    "investment": "Investment Plan",
    "exit_strategy": "Exit Strategy",
}

# 用户确认的关键词
CONFIRMATION_WORDS = ["yes", "sure", "ready", "let's go", "yep", "ok", "okay",
                      "sounds right", "correct", "that's right", "yeah", "yup", "go ahead"]

EDIT_WORDS = ["change", "edit", "update", "modify", "redo"]

EDIT_CONFIRMATION_WORDS = [
    "looks good",
    "done",
    "no",
    "finalize",
    "generate",
    "that's it",
    "all good",
    "perfect",
    "yes",
]

SECTION_ALIASES = {
    "problem": "problem",
    "product": "product",
    "features": "features",
    "feature": "features",
    "team": "team_traction",
    "traction": "team_traction",
    "team_traction": "team_traction",
    "investment": "investment",
    "funding": "investment",
    "exit": "exit_strategy",
    "exit_strategy": "exit_strategy",
}

llm = ChatAnthropic(model="claude-sonnet-4-6")


# ─── 流式输出辅助函数 ─────────────────────────────────────
def stream_response(prompt: str) -> str:
    """流式打印 LLM 输出，返回完整文字"""
    full_text = ""
    for chunk in llm.stream(prompt):
        print(chunk.content, end="", flush=True)
        full_text += chunk.content
    print()
    return full_text


# ─── 映射辅助函数 ─────────────────────────────────────────
def map_welcome_to_sections(conversation_history: str) -> dict:
    """从 welcome 对话中提取 problem 和 product 信息"""
    mapping_prompt = """<role>
You are an information extractor. Extract ONLY explicitly stated business information.
</role>

<task>
Read the conversation and extract information for these two fields only if clearly stated.
Return ONLY a JSON object — no explanation, no markdown.
</task>

<output_format>
{"problem": "explicit problem statement or empty string", "product": "explicit product description or empty string"}
</output_format>

<rules>
- "problem" = a specific pain point or problem being solved
- "product" = what the product/service actually does or offers
- Location alone does NOT count as problem
- Target demographic alone does NOT count as problem
- "a bubble tea store" alone does NOT count as product — needs more detail
- If not clearly stated, use empty string
</rules>

<examples>
Does NOT count as problem: "opening in Hamilton", "targeting females 15-40"
Does count as problem: "existing shops have bad quality", "no good options nearby"
Does NOT count as product: "a bubble tea store"
Does count as product: "a bubble tea store with 3-minute service and a loyalty app"
</examples>

<conversation>
""" + conversation_history + """
</conversation>"""

    response = llm.invoke(mapping_prompt)
    try:
        raw = response.content.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {}


# ─── Welcome 节点 ─────────────────────────────────────────
def welcome_node(state: FounderBuddyState):
    if state.get("welcome_done"):
        return {}
    
    current_count = state.get("welcome_question_count", 0)
    messages = state.get("messages", [])

    # 构建对话历史
    conversation_history = "\n".join([
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
        for m in messages
    ])

    # ── 修复重复问题：在代码层面检测用户确认，不依赖 LLM ──
    last_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content.strip().lower()
            break

    user_confirmed = any(word in last_user_msg for word in CONFIRMATION_WORDS)
    force_proceed = current_count >= 2

    # 用户确认或达到最大次数 → 直接进入映射，不再调用 LLM
    if user_confirmed or force_proceed:
        mapped = map_welcome_to_sections(conversation_history)

        updates = {
            "welcome_done": True,
            "current_section": "problem",
            "section_status": {
                "problem": "in_progress",
                "product": "pending",
                "features": "pending",
                "team_traction": "pending",
                "investment": "pending",
                "exit_strategy": "pending",
            },
            "messages": [AIMessage(content="Great! Let's build your business plan step by step.")],
        }

        # 只有明确回答了才映射
        if mapped.get("problem"):
            updates["problem"] = f"Q: What problem are you trying to solve?\nA: {mapped['problem']}"
        if mapped.get("product"):
            updates["product"] = f"Q: What is your product or service?\nA: {mapped['product']}"

        return updates

    # ── 正常流程：调用 LLM 追问或总结确认 ──
    assessment_prompt = f"""<role>
You are Founder Buddy, a friendly startup advisor helping entrepreneurs start their business plan.
You ONLY discuss the user's business idea. Never go off topic.
</role>

<conversation_history>
{conversation_history}
</conversation_history>

<task>
Determine whether the user's business idea is clear enough to proceed.
</task>

<instructions>
1. Read the full conversation history carefully
2. Note what is already known — NEVER ask about something already answered
3. If idea is clear enough → summarize in 1 sentence + ask "Does that sound right? Ready to move on?"
4. If idea is too vague → ask ONE specific follow-up question about what is missing
</instructions>

<what_counts_as_clear>
- We know what type of business they want to start
- We have at least one of: target customer, location, or core offering
- Full details are NOT needed — just enough context to begin
</what_counts_as_clear>

<hard_limits>
- You have {2 - current_count} follow-up question(s) remaining
- {"IMPORTANT: This is your last question. After this you MUST summarize and ask for confirmation." if current_count == 1 else ""}
- Keep response under 2 sentences
- Do NOT ask multiple questions at once
- Do NOT repeat anything already asked
</hard_limits>"""

    response = llm.invoke(assessment_prompt)
    response_text = response.content

    # interrupt 等用户回答
    user_answer = interrupt(response_text)
    return {
        "welcome_question_count": current_count + 1,
        "messages": [
            AIMessage(content=response_text),
            HumanMessage(content=user_answer),
        ],
    }


# ─── 章节节点 ───────────────────────────────────────────
def section_node(state: FounderBuddyState):
    section = state["current_section"]
    idx = state.get("current_question_index", 0)
    questions = QUESTIONS[section]

    # 如果 welcome 阶段已经映射了这个章节，直接跳过
    if state.get(section) and idx == 0:
        idx = len(questions)

    # 当前章节所有问题都问完了
    if idx >= len(questions):
        next_section_idx = SECTION_ORDER.index(section) + 1
        status = dict(state["section_status"])
        status[section] = "done"

        if next_section_idx >= len(SECTION_ORDER):
            return {
                "current_section": "done",
                "current_question_index": 0,
                "section_status": status,
            }

        next_section = SECTION_ORDER[next_section_idx]
        status[next_section] = "in_progress"
        return {
            "current_section": next_section,
            "current_question_index": 0,
            "section_status": status,
        }

    # 问当前问题
    question = questions[idx]
    label = SECTION_LABELS[section]
    question_msg = (
        f"[{label} — Question {idx + 1}/{len(questions)}]\n"
        f"{question}\n\n"
        f"(Type 'skip' to skip this question)"
    )

    user_answer = interrupt(question_msg)
    answer_text = "" if user_answer.strip().lower() in ["skip", "s"] else user_answer

    existing = state.get(section, "")
    updated = f"{existing}\nQ: {question}\nA: {answer_text}".strip()

    return {
        section: updated,
        "current_question_index": idx + 1,
        "messages": [AIMessage(content=question_msg)],
    }


# ─── 生成 BP 节点 ───────────────────────────────────────────
def generate_bp_node(state: FounderBuddyState):
    """所有章节完成后，流式生成完整商业计划书"""

    bp_prompt = f"""<role>
You are an experienced startup advisor and business plan writer.
Your job is to turn a founder's raw answers into a compelling, investor-ready business plan.
</role>

<founder_answers>
PROBLEM:
{state.get('problem') or 'Not provided'}

PRODUCT:
{state.get('product') or 'Not provided'}

FEATURES:
{state.get('features') or 'Not provided'}

TEAM & TRACTION:
{state.get('team_traction') or 'Not provided'}

INVESTMENT PLAN:
{state.get('investment') or 'Not provided'}

EXIT STRATEGY:
{state.get('exit_strategy') or 'Not provided'}
</founder_answers>

<task>
Write a complete, professional business plan based on the founder's answers above.
When answers are incomplete, vague, skipped, or uncertain, help the founder think through the missing area instead of leaving it blank.
</task>

<instructions>
1. Use the founder's actual words and details wherever they provided clear information.
2. Treat answers like "I don't know", "not sure", "skip", "s", empty answers, "N/A", or very generic responses as incomplete.
3. Do NOT write "To be determined".
4. For any incomplete or vague section:
   - Acknowledge that this area has not been fully defined yet.
   - Use information from OTHER completed sections to infer relevant strategic directions.
   - Offer 2-3 concrete, specific suggestions that would make sense for this founder's business.
   - Clearly label these as suggestions, not facts.
   - Write in an encouraging advisory tone, like a mentor helping the founder make the next decision.
5. If multiple sections are incomplete, connect the suggestions across sections so the business plan still feels coherent.
6. Make it compelling but honest — no exaggeration.
7. Use clear headings and bullet points where appropriate.
8. Write for a sophisticated investor audience while keeping the advisory voice supportive and practical.
</instructions>

<handling_incomplete_answers>
When a section is incomplete, use this pattern:
- Start with: "This has not been fully defined yet..."
- Then add: "Based on what is known so far, suggested directions include:"
- Provide 2-3 specific bullets grounded in the founder's business type, product, location, customers, traction, team, or funding context.
- End with one short sentence explaining why clarifying this area matters.

Example tone:
"This has not been fully defined yet — but based on the product and location, suggested directions include..."

Avoid generic advice. Every suggestion should clearly connect to details from the founder's other answers.
</handling_incomplete_answers>

<output_structure>
Write these 7 sections in order:
1. Executive Summary
2. Problem & Target User
3. Product & Solution
4. Core Features
5. Team & Traction
6. Financial Ask & Use of Funds
7. Exit Strategy
</output_structure>

<hard_limits>
- Do not present suggestions as confirmed facts.
- Do not invent traction, revenue, team members, partnerships, or financial projections.
- Do not add financial projections unless numbers were given.
- You may make clearly labeled strategic suggestions when information is incomplete, but they must be grounded in the founder's known answers.
- Keep each section focused and concise.
</hard_limits>"""

    print("\n=== Generating Your Business Plan ===\n")
    full_response = stream_response(bp_prompt)
    return {"messages": [AIMessage(content=full_response)]}


# ─── 编辑 BP 节点 ───────────────────────────────────────────
def detect_edit_section(user_text: str) -> str | None:
    """Detect whether the user asked to edit a known business plan section."""
    normalized = user_text.strip().lower().replace("-", "_").replace("&", " and ")
    has_edit_word = any(word in normalized for word in EDIT_WORDS)
    if not has_edit_word:
        return None

    for alias, section_key in SECTION_ALIASES.items():
        if alias in normalized:
            return section_key

    return None


def build_edit_status(section_key: str, current_status: dict) -> dict:
    """Set only the edited section back to in_progress."""
    status = dict(current_status)
    status[section_key] = "in_progress"
    return status


def complete_current_edit_status(state: FounderBuddyState) -> dict:
    status = dict(state.get("section_status", {}))
    section = state.get("current_section")
    if section in SECTION_ORDER:
        status[section] = "done"
    return status


def edit_node(state: FounderBuddyState):
    if state.get("edit_in_progress"):
        edit_prompt = (
            "Got it! Is there anything else you'd like to change? Or say "
            "'looks good' / 'done' to generate your final plan."
        )
    else:
        edit_prompt = (
            "Your business plan is ready! Would you like to edit anything? "
            "For example: 'edit problem' or 'change investment'. Or say "
            "'looks good' to finalize."
        )

    user_answer = interrupt(edit_prompt)
    section_key = detect_edit_section(user_answer)
    normalized_answer = user_answer.strip().lower()

    if section_key:
        return Command(goto="section", update={
            section_key: "",
            "current_section": section_key,
            "current_question_index": 0,
            "section_status": build_edit_status(section_key, complete_current_edit_status(state)),
            "edit_in_progress": True,
            "messages": [
                AIMessage(content=edit_prompt),
                HumanMessage(content=user_answer),
            ],
        })

    if any(word in normalized_answer for word in EDIT_CONFIRMATION_WORDS):
        return Command(goto="generate_bp", update={
            "current_section": "done",
            "current_question_index": 0,
            "section_status": complete_current_edit_status(state),
            "edit_in_progress": False,
            "messages": [
                AIMessage(content=edit_prompt),
                HumanMessage(content=user_answer),
            ],
        })

    return Command(goto="edit", update={
        "messages": [
            AIMessage(content=edit_prompt),
            HumanMessage(content=user_answer),
        ],
    })


# ─── 路由函数 ───────────────────────────────────────────
def welcome_router(state: FounderBuddyState):
    if state.get("welcome_done"):
        return "section"
    return "welcome"

def section_router(state: FounderBuddyState):
    if (
        state.get("edit_in_progress")
        and state.get("current_section") in QUESTIONS
        and state.get("current_question_index", 0) >= len(QUESTIONS[state["current_section"]])
    ):
        return "edit"
    if state["current_section"] == "done":
        return "generate_bp"
    return "section"


# ─── 建图 ───────────────────────────────────────────
builder = StateGraph(FounderBuddyState)
builder.add_node("welcome", welcome_node)
builder.add_node("section", section_node)
builder.add_node("generate_bp", generate_bp_node)
builder.add_node("edit", edit_node)

builder.add_edge(START, "welcome")
builder.add_conditional_edges("welcome", welcome_router, {
    "welcome": "welcome",
    "section": "section",
})
builder.add_conditional_edges("section", section_router, {
    "section": "section",
    "generate_bp": "generate_bp",
    "edit": "edit",
})
builder.add_edge("generate_bp", "edit")

memory = MemorySaver()
graph = builder.compile(checkpointer=memory)


# ─── 终端测试入口 ───────────────────────────────────────────
if __name__ == "__main__":
    import time
    config = {"configurable": {"thread_id": f"session-{int(time.time())}"}}

    initial_state = {
        "messages": [],
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

    print("=== Founder Buddy ===")
    print("Tell me about your idea!\n")

    first_input = input("You: ").strip()
    initial_state["messages"] = [HumanMessage(content=first_input)]

    graph.invoke(initial_state, config)

    while True:
        state = graph.get_state(config)

        if not state.tasks or not state.tasks[0].interrupts:
            break

        # A resumed graph can keep earlier interrupts on the task. Show the
        # latest one so we do not re-print the welcome confirmation prompt.
        interrupt_msg = state.tasks[0].interrupts[-1].value

        print(f"\nAgent: {interrupt_msg}")

        user_input = input("You: ").strip()
        graph.invoke(Command(resume=user_input), config)

    print("\n=== Done! ===")
