# Token Optimization Guide for Multi-Step A2A Agents

Practical techniques for reducing LLM token consumption by 60-80% in
production agents. Extracted from agents deployed on Kubernetes handling
enterprise workloads.

## The Problem

A naive ReAct agent with 10+ tools sends **all tool schemas on every LLM call**.
Each tool schema costs ~200-500 tokens. Over a 4-step interaction, that's:

```
10 tools × 300 tokens/tool × 4 LLM calls = 12,000 wasted tokens per request
```

Multiply by 1,000 daily requests and you're burning **12M tokens/day** just on
tool schemas the LLM never uses.

## Technique 1: Dynamic Tool Binding (60-80% savings)

**The single highest-impact optimization.**

Instead of binding all tools to every LLM call, bind only the tools referenced
in the planner's output.

### Before (all tools every call)

```python
# Every executor call sends ALL 10+ tool schemas
llm_with_tools = llm.bind_tools(ALL_TOOLS)
response = await llm_with_tools.ainvoke(messages)
```

### After (plan-relevant tools only)

```python
def select_tools_from_plan(plan: dict, tool_registry: dict) -> list:
    """Only bind tools the planner selected — saves 60-80% tokens."""
    names = []
    for name in plan.get("relevant_tools", []):
        if name in tool_registry and name not in names:
            names.append(name)
    for step in plan.get("steps", []):
        name = step.get("tool")
        if name in tool_registry and name not in names:
            names.append(name)
    return [tool_registry[n] for n in names] if names else list(tool_registry.values())

# Executor only sees 2-3 tools instead of 10+
active_tools = select_tools_from_plan(plan, self.tools_by_name)
llm_bound = llm.bind_tools(active_tools)
response = await llm_bound.ainvoke(messages)
```

### Impact

| Scenario | Tools bound | Schema tokens | Savings |
|----------|-----------|--------------|---------|
| All tools | 10 | ~3,000 | — |
| Plan: 2 tools | 2 | ~600 | **80%** |
| Plan: 4 tools | 4 | ~1,200 | **60%** |
| Fallback: all | 10 | ~3,000 | 0% |

## Technique 2: Staged Prompts (PEOS) (~40% savings)

Instead of one mega-prompt that handles planning, execution, observation, AND
synthesis, use separate focused prompts per node.

### Before (monolithic)

```python
SYSTEM_PROMPT = """You are an assistant that can:
1. Plan what tools to call (here are all 10 tools with full descriptions...)
2. Execute the tools
3. Check if results are complete
4. Format the final response with charts and quick replies
5. Handle errors gracefully
...
"""  # ~2,000 tokens
```

### After (staged)

```python
PLANNER_PROMPT = """Classify intent, select tools, output JSON plan."""  # ~600 tokens
OBSERVER_PROMPT = """Review results, return signals and patterns."""     # ~200 tokens
SYNTHESISER_PROMPT = """Format response as markdown with quick replies.""" # ~400 tokens
# Executor: uses ZERO system prompt — tool schemas ARE its prompt
```

### Why this works

- Planner doesn't need tool schemas (just names in text)
- Observer doesn't need tool schemas or formatting rules
- Synthesiser doesn't need tool schemas or planning rules
- Each node sees only what it needs

## Technique 3: Planner History Window (~70% savings after 5+ turns)

The planner only needs recent context to classify intent. Sending 20+ turns of
conversation history wastes tokens.

```python
# Planner sees only last 3 turns (6 messages: 3 human + 3 AI)
PLANNER_WINDOW = 6

history_msgs = [m for m in messages if not isinstance(m, SystemMessage)][-PLANNER_WINDOW:]
history_text = "\n".join(
    f"{type(m).__name__}: {m.content[:200]}"  # Also truncate per-message
    for m in history_msgs
)
```

### Impact by conversation length

| Turn # | Full history tokens | Windowed tokens | Savings |
|--------|-------------------|-----------------|---------|
| 1 | ~200 | ~200 | 0% |
| 5 | ~1,000 | ~600 | 40% |
| 10 | ~2,000 | ~600 | **70%** |
| 20 | ~4,000 | ~600 | **85%** |

## Technique 4: Result Truncation (prevents runaway costs)

Enterprise APIs can return massive payloads. A single SAP OData response with
`$expand` can be 100KB+. The LLM doesn't need all of it.

```python
MAX_RESULT_SIZE = 50_000  # 50KB cap

async def execute_tool(tool, args):
    result = await tool.ainvoke(args)
    result_str = str(result)
    if len(result_str) > MAX_RESULT_SIZE:
        result_str = result_str[:MAX_RESULT_SIZE] + "... [TRUNCATED]"
    return result_str
```

For the observer, truncate even further — it only needs summaries:

```python
# Observer sees 400 chars per tool result (not 50KB)
OBSERVER_CHAR_LIMIT = 400

summary = {k: v["result"][:OBSERVER_CHAR_LIMIT] for k, v in tool_results.items()}
```

## Technique 5: Fast Paths (100% savings for known intents)

Some intents don't need the LLM at all. Detect them and return immediately.

```python
FAST_PATH_TYPES = {"capability_inquiry", "out_of_scope", "conversational"}

# In synthesiser node:
if goal_type == "capability_inquiry":
    # Return built-in capability text — ZERO LLM calls
    return {"answer": CAPABILITIES_TEXT}

if goal_type == "out_of_scope":
    # Return canned redirect — ZERO LLM calls
    return {"answer": "That's outside my area. Try: ..."}
```

### Impact

If 20% of queries are capability/greeting/OOS (common in production):

```
100 requests × 20% fast path × ~4,000 tokens saved each = 80,000 tokens saved
```

## Technique 6: History Pruning (prevents unbounded growth)

Strip ToolMessages from conversation history. They contain `tool_call_id` 
references that become orphans on the next turn, AND they inflate history.

```python
def update_history(messages: list) -> list:
    """Keep only Human + AI messages. Strip System + Tool messages."""
    clean = []
    for m in messages:
        if isinstance(m, (SystemMessage, ToolMessage)):
            continue
        if isinstance(m, AIMessage):
            # Strip tool_calls to prevent orphan IDs
            content = m.content if isinstance(m.content, str) else str(m.content)
            if content.strip():
                clean.append(AIMessage(content=content))
            continue
        clean.append(m)
    return clean[-MAX_HISTORY:]  # Hard cap
```

## Technique 7: Concurrent Tool Execution (latency, not tokens)

Not a token optimization, but critical for UX. Fire parallel tool calls
simultaneously instead of sequentially.

```python
# Sequential: 3 tools × 2s each = 6s
for tc in tool_calls:
    result = await tool_map[tc["name"]].ainvoke(tc["args"])

# Concurrent: 3 tools = max(2s, 2s, 2s) = 2s
results = await asyncio.gather(
    *[tool_map[tc["name"]].ainvoke(tc["args"]) for tc in tool_calls]
)
```

## Combined Impact

For a typical 4-turn conversation with a 10-tool agent:

| Technique | Per-request savings | Cumulative |
|-----------|-------------------|------------|
| Dynamic tool binding | 2,400 tokens (80%) | 2,400 |
| Staged prompts | 1,600 tokens (40%) | 4,000 |
| Planner window | 800 tokens (turn 4+) | 4,800 |
| Result truncation | Variable (prevents spikes) | 4,800+ |
| Fast paths (20% of traffic) | ~4,000 per fast path | 5,600+ |
| History pruning | ~500 tokens (turn 4+) | 6,100+ |

**Total: ~6,000+ tokens saved per request (50-70% reduction)**

At 1,000 requests/day: **~6M fewer tokens/day**

## Implementation Checklist

- [ ] Dynamic tool binding in executor node
- [ ] Separate prompts per PEOS node (planner, observer, synthesiser)
- [ ] Planner history window (last 3 turns)
- [ ] Result truncation (50KB cap for executor, 400 chars for observer)
- [ ] Fast paths for capability inquiry, greetings, out-of-scope
- [ ] History pruning (strip ToolMessages, cap at 40 messages)
- [ ] Concurrent tool execution (asyncio.gather)
- [ ] LLM timeout per call (25s) and E2E timeout (55s)

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | Fix |
|-------------|-------------|-----|
| Binding all tools every call | Wastes 2-3K tokens/call | Dynamic tool binding |
| Single monolithic prompt | Every node pays for irrelevant instructions | PEOS staged prompts |
| Unbounded conversation history | Tokens grow linearly with turns | History windowing + pruning |
| No result truncation | One large API response can cost 10K+ tokens | 50KB cap |
| LLM call for "what can you do?" | Wastes ~4K tokens on deterministic output | Fast path |
| Sequential tool calls | 3× latency for no reason | asyncio.gather |
