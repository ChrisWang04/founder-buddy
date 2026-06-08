import asyncio
from dotenv import load_dotenv
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import tools_condition

load_dotenv()


# ─── State ────────────────────────────────────────────────────────────────────


class FounderBuddyState(TypedDict):
    messages: Annotated[list, add_messages]
    current_section: str
    last_completed_section: str   # set by tools_node; read by memory_updater
    section_status: dict
    problem: str
    product: str
    features: str
    team_traction: str
    investment: str
    exit_strategy: str


SECTION_ORDER = ["problem", "product", "features", "team_traction", "investment", "exit_strategy"]

SECTION_LABELS = {
    "problem": "Problem",
    "product": "Product",
    "features": "Features",
    "team_traction": "Team & Traction",
    "investment": "Investment Plan",
    "exit_strategy": "Exit Strategy",
}

SECTION_PROMPTS = {
    "problem": """You are collecting the PROBLEM section.
Goal: understand the pain point, who experiences it, and how it is currently solved (poorly).
Ask AT MOST 3 questions total, then call complete_section(content="concise summary").
Cover: (1) the pain point, (2) who has it, (3) existing bad solutions.""",

    "product": """You are collecting the PRODUCT section.
Goal: understand what the product/service is and how it solves the problem.
Ask AT MOST 3 questions total, then call complete_section(content="concise summary").
Cover: what it is, how it works, what makes it different.""",

    "features": """You are collecting the FEATURES section.
Goal: understand the core capabilities (up to 5) and the standout feature.
Ask AT MOST 3 questions total, then call complete_section(content="concise summary").""",

    "team_traction": """You are collecting the TEAM & TRACTION section.
Goal: understand who is building this and any early validation (users, revenue, partnerships).
Ask AT MOST 3 questions total. "None yet" is a valid traction answer.
When done, call complete_section(content="concise summary").""",

    "investment": """You are collecting the INVESTMENT section.
Goal: understand the funding ask and planned use of funds.
Ask AT MOST 3 questions total, then call complete_section(content="concise summary").""",

    "exit_strategy": """You are collecting the EXIT STRATEGY section.
Goal: understand the long-term vision — acquisition, IPO, or lifestyle business.
Ask AT MOST 3 questions total, then call complete_section(content="concise summary").
This is the last section — after calling complete_section the business plan will be generated automatically.""",
}


# ─── Tools ────────────────────────────────────────────────────────────────────


@tool
def complete_section(content: str) -> str:
    """Mark the current section as complete and advance to the next.

    Args:
        content: A concise summary of what was collected for this section.
    """
    return "Section complete."


@tool
def modify_section(section: str) -> str:
    """Go back to re-collect a previously completed section.
    Use when the user wants to change or improve a previous answer.

    Args:
        section: One of: problem, product, features, team_traction, investment, exit_strategy
    """
    return f"Now editing {section}."


llm = ChatAnthropic(model="claude-sonnet-4-6")          # BP generation (implementation_node)
llm_qa = ChatAnthropic(model="claude-haiku-4-5-20251001") # Q&A (assistant_node) — 5-10x faster
_tools = [complete_section, modify_section]
llm_with_tools = llm_qa.bind_tools(_tools)


# ─── Nodes ────────────────────────────────────────────────────────────────────


async def initialize_node(state: FounderBuddyState, config: RunnableConfig) -> dict:
    """Validate and normalize state on every invocation."""
    updates: dict = {}

    current = state.get("current_section", SECTION_ORDER[0])
    if current not in SECTION_ORDER and current != "done":
        updates["current_section"] = SECTION_ORDER[0]

    # Bootstrap section_status on very first message
    if not state.get("section_status"):
        updates["section_status"] = {
            **{s: "pending" for s in SECTION_ORDER},
            SECTION_ORDER[0]: "in_progress",
        }

    return updates


async def assistant_node(state: FounderBuddyState, config: RunnableConfig) -> dict:
    """Conversational Q&A — collects section info via tool calls. Never generates the BP."""
    current = state.get("current_section", SECTION_ORDER[0])
    if current not in SECTION_ORDER:
        current = SECTION_ORDER[0]

    status_lines = "\n".join(
        f"  {SECTION_LABELS[s]}: {state.get('section_status', {}).get(s, 'pending')}"
        for s in SECTION_ORDER
    )
    collected_parts = [
        f"  {SECTION_LABELS[s]}: {state.get(s, '')}"
        for s in SECTION_ORDER
        if state.get(s, "")
    ]
    collected_str = "\n".join(collected_parts) if collected_parts else "  Nothing collected yet."

    section_guidance = SECTION_PROMPTS.get(current, "Continue the conversation.")
    system_content = f"""You are Founder Buddy, an AI startup advisor helping founders build a business plan.

Current section: {SECTION_LABELS.get(current, current)}
{section_guidance}

Section progress:
{status_lines}

Collected so far:
{collected_str}

Rules:
- Be conversational and encouraging. Keep replies to 2-4 sentences.
- Ask ONE question at a time.
- Do NOT use markdown formatting (no **bold**, no bullet points, no headers) — plain text only.
- When you have enough info for the current section, call complete_section(content="summary").
- If the user wants to change a previous answer, call modify_section(section="section_name").
- Do NOT jump ahead — collect the current section fully before moving on."""

    response = await llm_with_tools.ainvoke(
        [SystemMessage(content=system_content)] + state["messages"],
        config,
    )
    return {"messages": [response]}


def tools_node(state: FounderBuddyState) -> dict:
    """Execute tool calls and update section state."""
    messages = state["messages"]
    last_msg = messages[-1] if messages else None

    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {}

    state_updates: dict = {}
    tool_messages: list = []

    for tc in last_msg.tool_calls:
        name = tc["name"]
        args = tc.get("args", {})

        if name == "complete_section":
            current = state.get("current_section", "")
            if current not in SECTION_ORDER:
                tool_messages.append(ToolMessage(
                    content="No active section to complete.",
                    tool_call_id=tc["id"],
                ))
                continue

            state_updates[current] = args.get("content", "")
            state_updates["last_completed_section"] = current

            idx = SECTION_ORDER.index(current)
            status = dict(state.get("section_status", {}))
            status[current] = "done"

            if idx + 1 < len(SECTION_ORDER):
                next_sec = SECTION_ORDER[idx + 1]
                status[next_sec] = "in_progress"
                state_updates["current_section"] = next_sec
                result = f"'{SECTION_LABELS[current]}' complete. Moving to '{SECTION_LABELS[next_sec]}'."
            else:
                state_updates["current_section"] = "done"
                result = f"'{SECTION_LABELS[current]}' complete. All sections done — generating business plan."

            state_updates["section_status"] = status
            tool_messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

        elif name == "modify_section":
            target = args.get("section", "")
            if target not in SECTION_ORDER:
                tool_messages.append(ToolMessage(
                    content=f"Unknown section '{target}'. Valid: {', '.join(SECTION_ORDER)}",
                    tool_call_id=tc["id"],
                ))
                continue

            status = dict(state.get("section_status", {}))
            status[target] = "in_progress"
            state_updates["section_status"] = status
            state_updates["current_section"] = target
            state_updates[target] = ""
            state_updates["last_completed_section"] = ""
            tool_messages.append(ToolMessage(
                content=f"Switched to editing '{SECTION_LABELS[target]}'. Previous content cleared.",
                tool_call_id=tc["id"],
            ))

    return {**state_updates, "messages": tool_messages}


async def memory_updater_node(state: FounderBuddyState, config: RunnableConfig) -> dict:
    """Persist completed section summaries to Supabase."""
    last_section = state.get("last_completed_section", "")

    if last_section and last_section in SECTION_ORDER:
        conv_id = config.get("configurable", {}).get("conversation_id")
        if conv_id:
            from db import save_message as db_save
            content = state.get(last_section, "")
            label = SECTION_LABELS.get(last_section, last_section)
            await asyncio.to_thread(
                db_save,
                conv_id,
                "system",
                f"[Section: {label}]\n{content}",
            )

    return {}


async def implementation_node(state: FounderBuddyState, config: RunnableConfig) -> dict:
    """Generate the investor-ready business plan from all collected sections."""
    collected_parts = [
        f"  {SECTION_LABELS[s]}: {state.get(s, '')}"
        for s in SECTION_ORDER
        if state.get(s, "")
    ]
    collected_str = "\n".join(collected_parts) if collected_parts else "  Nothing collected yet."

    system_content = f"""You are Founder Buddy, an AI startup advisor.
All sections are complete. Write a comprehensive, investor-ready business plan.

Collected information:
{collected_str}

Write the full plan with these sections in order:
1. Executive Summary
2. Problem & Target User
3. Product & Solution
4. Core Features
5. Team & Traction
6. Financial Ask & Use of Funds
7. Exit Strategy

Be specific and compelling. Use the founder's actual words. Do NOT call any tools."""

    response = await llm.ainvoke(
        [SystemMessage(content=system_content)] + state["messages"],
        config,
    )
    return {"messages": [response]}


def route_after_memory_updater(state: FounderBuddyState) -> Literal["implementation", "assistant"]:
    if state.get("current_section") == "done":
        return "implementation"
    return "assistant"


# ─── Graph ────────────────────────────────────────────────────────────────────

builder = StateGraph(FounderBuddyState)
builder.add_node("initialize", initialize_node)
builder.add_node("assistant", assistant_node)
builder.add_node("tools", tools_node)
builder.add_node("memory_updater", memory_updater_node)
builder.add_node("implementation", implementation_node)

builder.add_edge(START, "initialize")
builder.add_edge("initialize", "assistant")
builder.add_conditional_edges("assistant", tools_condition)
builder.add_edge("tools", "memory_updater")
builder.add_conditional_edges(
    "memory_updater",
    route_after_memory_updater,
    {"implementation": "implementation", "assistant": "assistant"},
)
builder.add_edge("implementation", END)


# ─── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time
    from langgraph.checkpoint.memory import MemorySaver

    _graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": f"session-{int(time.time())}"}}

    initial_state = {
        "messages": [],
        "current_section": "problem",
        "last_completed_section": "",
        "section_status": {},
        "problem": "", "product": "", "features": "",
        "team_traction": "", "investment": "", "exit_strategy": "",
    }

    async def run():
        print("=== Founder Buddy ===\n")
        first = input("You: ").strip()
        initial_state["messages"] = [HumanMessage(content=first)]
        await _graph.ainvoke(initial_state, config)

        while True:
            st = await _graph.aget_state(config)
            last_ai = next(
                (m for m in reversed(st.values["messages"])
                 if isinstance(m, AIMessage) and not m.tool_calls and m.content),
                None,
            )
            if last_ai:
                content = last_ai.content
                if isinstance(content, list):
                    content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
                print(f"\nAgent: {content}")

            if st.values.get("current_section") == "done":
                print("\n=== Business Plan Generated ===")
                break

            user_input = input("You: ").strip()
            if not user_input:
                continue
            await _graph.ainvoke({"messages": [HumanMessage(content=user_input)]}, config)

    asyncio.run(run())
