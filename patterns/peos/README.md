# PEOS Pattern — Planner→Executor→Observer→Synthesiser

A production-grade multi-step agent architecture using LangGraph.

**PEOS** decomposes complex queries into a 4-node state machine where each node
has a focused role, separate prompt, and minimal token footprint.

## Why PEOS?

Most agent samples use a single-loop ReAct pattern: the LLM sees all tools, all
history, and decides what to do next. This works for toy demos but breaks down at
scale:

| Problem | ReAct | PEOS |
|---------|-------|------|
| Token cost | All tools loaded every turn (~3-5K tokens) | Only plan-relevant tools loaded (60-80% less) |
| Prompt bloat | One mega-prompt for everything | Focused prompt per node (~40% less) |
| Quality | LLM conflates planning with execution | Planning and execution are separate concerns |
| Observability | Single black box | 4 observable checkpoints |
| Error handling | Single retry loop | Observer can request targeted retries |

## Architecture

```
        ┌────────────────────────────────────────────────────────┐
        │                    PEOS State Machine                  │
        │                                                        │
  User  │  ┌──────────┐    ┌──────────┐    ┌──────────┐         │
  Query──┼─▶│ PLANNER  │───▶│ EXECUTOR │◀──▶│ OBSERVER │         │
        │  │ 1 LLM    │    │ 1+ LLM   │    │ 1 LLM   │         │
        │  │ call      │    │ calls    │    │ call     │         │
        │  └──────────┘    └──────────┘    └──────────┘         │
        │       │               │               │                │
        │       │ plan JSON     │ tool results  │ signals        │
        │       │               │               │                │
        │       │          ┌──────────────┐     │                │
        │       └─────────▶│ SYNTHESISER  │◀────┘                │
        │    (fast paths)  │ 0-1 LLM call │                      │
        │                  └──────┬───────┘                      │
        │                         │                              │
        └─────────────────────────┼──────────────────────────────┘
                                  │
                            Final Response
```

## Node Responsibilities

### 1. Planner (1 LLM call)
- **Input**: User query + last 3 conversation turns (windowed)
- **Output**: JSON plan with `goal_type`, `relevant_tools[]`, `steps[]`
- **Token strategy**: Sees NO tool schemas, only a text list of tool names + descriptions
- **Fast paths**: Greetings, "what can you do?", out-of-scope → skip executor entirely

### 2. Executor (1+ LLM calls, looped)
- **Input**: Messages + plan steps
- **Output**: Tool call results
- **Token strategy**: Only tools in `relevant_tools` are bound (dynamic tool binding)
- **HITL gate**: Write operations require user confirmation before execution
- **Safety**: 50KB result truncation, tool policy enforcement

### 3. Observer (1 LLM call)
- **Input**: Truncated tool results (400 chars per tool)
- **Output**: Signals (anomalies, patterns, risk flags)
- **Token strategy**: Sees summaries, not full results

### 4. Synthesiser (0-1 LLM calls)
- **Input**: All messages + observer signals
- **Output**: Formatted response (text + structured data)
- **Fast paths**: Capability inquiry, HITL prompts, out-of-scope → 0 LLM calls
- **Token strategy**: Separate focused prompt, no tool schemas

## Token Savings Breakdown

| Technique | Where Applied | Typical Savings |
|-----------|---------------|-----------------|
| Dynamic tool binding | Executor | 60-80% per executor call |
| Staged prompts | All nodes | ~40% vs monolithic prompt |
| 3-turn planner window | Planner | ~70% after 5+ turns |
| Result truncation (50KB) | Executor | Prevents runaway costs |
| Observer result summaries | Observer | ~80% vs full results |
| History windowing (40 msgs) | All nodes | Bounded memory |
| Fast paths (0 LLM calls) | Synthesiser | 100% for known intents |

## Implementation

See [peos_pattern.py](peos_pattern.py) for a framework-agnostic reference implementation
(~200 lines) that you can adapt to any domain.

## Adapting PEOS to Your Domain

1. **Define your tool registry** — list all tools your agent can use
2. **Write a planner prompt** — describe tool groups, goal types, and routing rules
3. **Write an observer prompt** — what signals matter for your domain?
4. **Write a synthesiser prompt** — how should responses be formatted?
5. **Implement fast paths** — which intents can be answered without LLM calls?
6. **Add HITL** — which tools need user confirmation?

The PEOS graph structure stays the same — only the prompts and tools change.

## License

Apache-2.0
