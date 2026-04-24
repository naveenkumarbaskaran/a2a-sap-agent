"""
PEOS Pattern — Planner → Executor → Observer → Synthesiser

A framework-agnostic reference implementation of the PEOS multi-step agent
architecture using LangGraph. This pattern works with any LLM provider
(OpenAI, Anthropic, Google, etc.) via litellm.

This file is self-contained and can be adapted to any domain by changing:
1. TOOLS — your tool registry
2. PLANNER_PROMPT — your planning instructions
3. OBSERVER_PROMPT — your quality evaluation criteria
4. SYNTHESISER_PROMPT — your response formatting rules
5. FAST_PATH_TYPES — intents that skip the executor

Usage:
    agent = PEOSAgent(model="gpt-4o", tools=YOUR_TOOLS)
    async for event in agent.stream("your query", context_id="session-1"):
        print(event)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Annotated, Any, AsyncGenerator, Optional, TypedDict

import litellm
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

litellm.drop_params = True
logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATE SCHEMA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PEOSState(TypedDict):
    """State flowing through the PEOS graph."""
    messages: Annotated[list[BaseMessage], add_messages]
    plan: Optional[dict]                # Planner output: goal_type, steps, relevant_tools
    tool_results: dict[str, Any]        # Accumulated tool call results
    executor_iterations: int            # Loop counter (safety bound)
    observer_signals: list[str]         # Observer findings
    final_answer: Optional[str]         # Synthesiser output
    context_id: str                     # Session ID for multi-turn
    human_input_required: bool          # HITL gate flag


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION (override these for your domain)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT_CONFIG = {
    "max_executor_iterations": 10,      # Max executor→observer loops
    "max_history_messages": 40,         # Conversation history cap
    "planner_history_window": 6,        # Messages planner sees (3 turns × 2)
    "result_truncation_bytes": 50_000,  # Max tool result size
    "observer_summary_chars": 400,      # Chars per tool result the observer sees
    "e2e_timeout_seconds": 55.0,        # Total timeout for one request
    "llm_timeout_seconds": 25,          # Per-LLM-call timeout
    "fast_path_types": {                # Goal types that skip executor
        "conversational", "capability_inquiry", "out_of_scope",
    },
    "write_action_types": set(),        # Goal types requiring HITL confirmation
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PEOS AGENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PEOSAgent:
    """Generic PEOS agent — adapt to any domain by passing tools and prompts.
    
    Args:
        model: LLM model name (any litellm-compatible string)
        tools: List of LangChain tools
        planner_prompt: System prompt for the planner node
        observer_prompt: System prompt for the observer node
        synthesiser_prompt: System prompt for the synthesiser node
        config: Override DEFAULT_CONFIG values
        write_action_types: Goal types that require HITL confirmation
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        tools: list | None = None,
        planner_prompt: str = "You are a planning assistant. Output JSON with goal_type, relevant_tools, and steps.",
        observer_prompt: str = "Review tool results. Return JSON with signals and patterns.",
        synthesiser_prompt: str = "Synthesize tool results into a helpful response.",
        config: dict | None = None,
        write_action_types: set[str] | None = None,
    ):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        if write_action_types:
            self.config["write_action_types"] = write_action_types

        self.llm = ChatLiteLLM(model=model, timeout=self.config["llm_timeout_seconds"])
        self.tools = tools or []
        self.tool_map = {t.name: t for t in self.tools}
        self.tools_by_name = {t.name: t for t in self.tools}

        self.planner_prompt = planner_prompt
        self.observer_prompt = observer_prompt
        self.synthesiser_prompt = synthesiser_prompt

        self._history: dict[str, list[BaseMessage]] = defaultdict(list)
        self.graph = self._build_graph()

    # ── Dynamic Tool Binding ────────────────────────────────────────────────
    # KEY OPTIMIZATION: Only bind tools referenced in the plan to the LLM.
    # A typical plan references 2-3 of 10+ available tools.
    # This saves 60-80% of tool schema tokens per executor call.

    def _select_tools_from_plan(self, plan: Optional[dict]) -> list:
        if not plan:
            return self.tools

        names: list[str] = []
        for n in plan.get("relevant_tools", []):
            if isinstance(n, str) and n in self.tools_by_name and n not in names:
                names.append(n)
        for step in plan.get("steps", []) or []:
            n = step.get("tool") if isinstance(step, dict) else None
            if isinstance(n, str) and n in self.tools_by_name and n not in names:
                names.append(n)

        return [self.tools_by_name[n] for n in names] if names else self.tools

    # ── Graph Construction ──────────────────────────────────────────────────

    def _build_graph(self):
        agent = self
        cfg = self.config

        async def planner_node(state: PEOSState) -> dict:
            """NODE 1: Classify intent and build execution plan.
            
            Cost: 1 LLM call
            Input: User query + windowed history (last N messages)
            Output: JSON plan with goal_type, relevant_tools, steps
            
            The planner sees NO tool schemas (just tool names in the prompt),
            keeping its context small. The 3-turn window means planner cost
            stays constant regardless of conversation length.
            """
            user_msg = next(
                (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), ""
            )
            # Windowed history: planner only sees last N messages
            window = cfg["planner_history_window"]
            history_msgs = [m for m in state["messages"] if not isinstance(m, SystemMessage)][-window:]
            history_text = "\n".join(
                f"{type(m).__name__}: {(m.content[:200] if isinstance(m.content, str) else '(structured)')}"
                for m in history_msgs
            ) or "(no history)"

            try:
                raw = await agent.llm.ainvoke([
                    SystemMessage(content=agent.planner_prompt),
                    HumanMessage(content=f"History:\n{history_text}\n\nUser: {user_msg}"),
                ])
                content = raw.content.strip() if isinstance(raw.content, str) else "{}"
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                plan = json.loads(content)
            except Exception as e:
                logger.warning("[PLANNER] fallback: %s", e)
                plan = {"goal_type": "conversational", "relevant_tools": [], "steps": []}

            return {
                "plan": plan,
                "tool_results": {},
                "executor_iterations": 0,
                "observer_signals": [],
                "final_answer": None,
                "human_input_required": False,
            }

        async def executor_node(state: PEOSState) -> dict:
            """NODE 2: Execute tools from the plan.
            
            Cost: 1 LLM call per iteration (tool selection + calling)
            
            Key optimizations:
            - Dynamic tool binding: only plan-relevant tools are bound
            - Concurrent tool execution: multiple tool calls fire in parallel
            - Result truncation: 50KB cap prevents runaway costs
            - HITL gate: write operations require user confirmation first
            """
            iterations = state.get("executor_iterations", 0)
            tool_results = dict(state.get("tool_results", {}))
            messages = list(state["messages"])
            plan = state.get("plan") or {}

            # ── HITL Gate ───────────────────────────────────────────────────
            goal = plan.get("goal_type", "")
            if goal in cfg["write_action_types"]:
                latest = next(
                    (m.content for m in reversed(messages) if isinstance(m, HumanMessage) and isinstance(m.content, str)),
                    "",
                )
                if not any(kw in latest.lower() for kw in ("confirm", "approved", "go ahead")):
                    return {
                        "messages": [AIMessage(content="⚠️ Confirmation required. Reply 'confirm' to proceed.")],
                        "tool_results": tool_results,
                        "executor_iterations": iterations + 1,
                        "human_input_required": True,
                    }

            # Inject plan summary on first iteration
            if iterations == 0 and plan.get("steps"):
                summary = "\n".join(
                    f"Step {i+1}: {s.get('tool')} — {s.get('reason', '')}"
                    for i, s in enumerate(plan["steps"])
                )
                messages.append(SystemMessage(content=f"Plan:\n{summary}\nExecute now."))

            # ── Dynamic tool binding (the big savings) ──────────────────────
            active_tools = agent._select_tools_from_plan(plan)
            llm_bound = agent.llm.bind_tools(active_tools)
            response = await llm_bound.ainvoke(messages)
            new_messages: list[BaseMessage] = [response]

            if hasattr(response, "tool_calls") and response.tool_calls:
                async def _call(tc):
                    try:
                        result = await agent.tool_map[tc["name"]].ainvoke(tc["args"])
                        result_str = str(result)
                        # Result truncation
                        cap = cfg["result_truncation_bytes"]
                        if len(result_str) > cap:
                            result_str = result_str[:cap] + "... [TRUNCATED]"
                        return (
                            ToolMessage(content=result_str, tool_call_id=tc["id"]),
                            {"tool": tc["name"], "args": tc["args"], "result": result_str},
                        )
                    except Exception as e:
                        logger.exception("Tool %s failed", tc["name"])
                        return (
                            ToolMessage(content=f"Tool {tc['name']} failed.", tool_call_id=tc["id"]),
                            None,
                        )

                results = await asyncio.gather(*[_call(tc) for tc in response.tool_calls])
                for msg, entry in results:
                    new_messages.append(msg)
                    if entry:
                        tool_results[f"{entry['tool']}_{msg.tool_call_id}"] = entry

            return {
                "messages": new_messages,
                "tool_results": tool_results,
                "executor_iterations": iterations + 1,
                "human_input_required": False,
            }

        async def observer_node(state: PEOSState) -> dict:
            """NODE 3: Evaluate result quality and detect anomalies.
            
            Cost: 1 LLM call
            Input: Truncated summaries of tool results (not full results)
            Output: Signals, patterns, risk flags
            
            The observer sees only the first N chars of each tool result,
            saving significant tokens on large SAP API responses.
            """
            tool_results = state.get("tool_results", {})
            if not tool_results:
                return {"observer_signals": []}

            char_limit = cfg["observer_summary_chars"]
            summary = json.dumps(
                {k: v.get("result", "")[:char_limit] for k, v in tool_results.items()},
                indent=2,
            )

            try:
                resp = await agent.llm.ainvoke([
                    SystemMessage(content=agent.observer_prompt),
                    HumanMessage(content=f"Tool results:\n{summary}"),
                ])
                content = resp.content.strip() if isinstance(resp.content, str) else "{}"
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                parsed = json.loads(content)
            except Exception as e:
                logger.warning("[OBSERVER] fallback: %s", e)
                parsed = {"signals": [], "patterns": []}

            signals = list(parsed.get("signals", [])) + [
                f"Pattern: {p}" for p in parsed.get("patterns", [])
            ]
            return {"observer_signals": signals, "tool_results": tool_results}

        async def synthesiser_node(state: PEOSState) -> dict:
            """NODE 4: Format the final response.
            
            Cost: 0-1 LLM calls
            
            Fast paths (0 LLM calls):
            - Capability inquiry → return built-in text
            - HITL prompts → pass through confirmation request
            - Out of scope → return canned redirect
            
            Full synthesis (1 LLM call):
            - Filters orphan ToolMessages to prevent API errors
            - Injects observer signals as context
            - Uses a focused synthesis prompt (no tool schemas)
            """
            plan = state.get("plan") or {}
            goal = plan.get("goal_type", "")

            # Fast path: HITL
            if state.get("human_input_required"):
                msg = next(
                    (m.content for m in reversed(state["messages"]) if isinstance(m, AIMessage)),
                    "Confirmation required.",
                )
                return {"final_answer": msg, "messages": [AIMessage(content=msg)], "human_input_required": True}

            # Fast path: no-tool intents
            if goal in cfg["fast_path_types"] and not state.get("tool_results"):
                answer = plan.get("goal_summary", "How can I help?")
                return {"final_answer": answer, "messages": [AIMessage(content=answer)]}

            # Full synthesis: filter orphan ToolMessages
            valid_ids: set[str] = set()
            for m in state["messages"]:
                if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls:
                    for tc in m.tool_calls:
                        valid_ids.add(tc["id"])

            synth_msgs: list[BaseMessage] = []
            for m in state["messages"]:
                if isinstance(m, SystemMessage):
                    continue
                if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", "") not in valid_ids:
                    continue
                synth_msgs.append(m)

            signals = state.get("observer_signals", [])
            if signals:
                synth_msgs.append(SystemMessage(content="Observer signals:\n" + "\n".join(f"- {s}" for s in signals)))

            try:
                resp = await agent.llm.ainvoke([SystemMessage(content=agent.synthesiser_prompt)] + synth_msgs)
                answer = resp.content if isinstance(resp.content, str) else str(resp.content)
            except Exception:
                answer = "I encountered an error generating the response. Please try again."
                logger.exception("[SYNTHESISER] Error")

            return {"final_answer": answer, "messages": [AIMessage(content=answer)]}

        # ── Routing ─────────────────────────────────────────────────────────

        def route_after_planner(state: PEOSState) -> str:
            plan = state.get("plan") or {}
            if not plan.get("steps") or plan.get("goal_type", "") in cfg["fast_path_types"]:
                return "synthesiser"
            return "executor"

        def route_after_executor(state: PEOSState) -> str:
            if state.get("human_input_required"):
                return "synthesiser"
            if state.get("executor_iterations", 0) >= cfg["max_executor_iterations"]:
                return "observer"
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "executor"
            return "observer"

        # ── Assemble ────────────────────────────────────────────────────────

        builder = StateGraph(PEOSState)
        builder.add_node("planner", planner_node)
        builder.add_node("executor", executor_node)
        builder.add_node("observer", observer_node)
        builder.add_node("synthesiser", synthesiser_node)

        builder.add_edge(START, "planner")
        builder.add_conditional_edges("planner", route_after_planner,
            {"executor": "executor", "synthesiser": "synthesiser"})
        builder.add_conditional_edges("executor", route_after_executor,
            {"executor": "executor", "observer": "observer", "synthesiser": "synthesiser"})
        builder.add_edge("observer", "synthesiser")
        builder.add_edge("synthesiser", END)

        return builder.compile()

    # ── History Management ──────────────────────────────────────────────────

    def _build_messages(self, query: str, context_id: str) -> list[BaseMessage]:
        return self._history[context_id] + [HumanMessage(content=query)]

    def _update_history(self, context_id: str, messages: list[BaseMessage]):
        """Keep Human + AI messages only. Strip ToolMessages to prevent orphan IDs on next turn."""
        clean: list[BaseMessage] = []
        for m in messages:
            if isinstance(m, (SystemMessage, ToolMessage)):
                continue
            if isinstance(m, AIMessage):
                content = m.content if isinstance(m.content, str) else str(m.content)
                if content and content.strip():
                    clean.append(AIMessage(content=content))
                continue
            clean.append(m)
        cap = self.config["max_history_messages"]
        self._history[context_id] = clean[-cap:]

    # ── Public API ──────────────────────────────────────────────────────────

    async def stream(self, query: str, context_id: str = "default") -> AsyncGenerator[dict, None]:
        """Run the PEOS graph and stream results."""
        yield {"status": "working", "content": "Analyzing..."}

        state: PEOSState = {
            "messages": self._build_messages(query, context_id),
            "plan": None,
            "tool_results": {},
            "executor_iterations": 0,
            "observer_signals": [],
            "final_answer": None,
            "context_id": context_id,
            "human_input_required": False,
        }

        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(state),
                timeout=self.config["e2e_timeout_seconds"],
            )
        except asyncio.TimeoutError:
            yield {"status": "error", "content": "Request timed out. Try a simpler query."}
            return

        self._update_history(context_id, result["messages"])

        answer = result.get("final_answer", "No response generated.")
        requires_input = result.get("human_input_required", False)

        yield {
            "status": "input_required" if requires_input else "completed",
            "content": answer,
        }
