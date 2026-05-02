# Human-in-the-Loop (HITL) Write Safety Pattern

A pattern for requiring explicit user confirmation before an AI agent performs
write/mutating operations on enterprise systems.

## Why HITL for Write Operations?

AI agents reading data is low-risk. AI agents **writing** data can cause real
damage — deleting records, changing statuses, posting transactions. HITL provides
an **intent safety net and audit trail** before any mutation happens.

```
User: "Set order 4000045 to TECO"
Agent: ⚠️ Confirmation required: I'm about to set TECO for 4000045. Reply 'confirm' to proceed.
User: "confirm"
Agent: ✅ Order 4000045 set to Technically Complete (TECO).
```

## Architecture

```
                                     ┌──────────┐
User ──▶ Planner ──▶ Executor ──────▶│ HITL     │
                                     │ Gate     │
                                     └────┬─────┘
                                          │
                          ┌───────────────┴───────────────┐
                          │                               │
                    No confirmation              Has confirmation
                          │                               │
                          ▼                               ▼
                 Return prompt to user           Execute write tool
                 (input_required=true)           (tool_policy check)
                                                         │
                                                         ▼
                                                 Return result
```

## Implementation

### 1. Classify Write Actions in the Planner

```python
# planner output
{
    "goal_type": "action_teco",         # ← write action type
    "goal_summary": "Set order 4000045 to TECO",
    "relevant_tools": ["set_orders_to_teco"],
    "steps": [
        {"tool": "set_orders_to_teco", "args": {"order_ids": ["4000045"]}, "reason": "User requested TECO"}
    ]
}
```

### 2. HITL Gate in the Executor

The executor checks two conditions before executing a write tool:
1. Is this a write action type? (from planner's `goal_type`)
2. Has the user confirmed? (keyword detection in latest message)

```python
# In the executor node
WRITE_ACTION_TYPES = {"action_teco", "action_unteco", "action_delete"}

def has_write_confirmation(text: str) -> bool:
    """Check if user message contains explicit confirmation."""
    if not text:
        return False
    return bool(re.search(
        r"\b(confirm|confirmed|approved|yes proceed|go ahead)\b",
        text.lower(),
    ))

async def executor_node(state):
    plan = state.get("plan", {})
    goal_type = plan.get("goal_type", "")
    
    # HITL gate: check if this is a write action
    if goal_type in WRITE_ACTION_TYPES:
        latest_user_msg = get_latest_user_message(state["messages"])
        
        if not has_write_confirmation(latest_user_msg):
            # Extract what we're about to do for the confirmation prompt
            order_ids = extract_order_ids_from_plan(plan)
            action_label = "set TECO" if goal_type == "action_teco" else "reset TECO"
            order_text = ", ".join(order_ids) or "the requested order(s)"
            
            return {
                "messages": [AIMessage(
                    content=f"⚠️ **Confirmation required**: I'm about to {action_label} "
                            f"for {order_text}. Reply 'confirm' to proceed."
                )],
                "human_input_required": True,  # ← signals A2A to set input_required
            }
    
    # User confirmed → proceed with execution
    # ... normal tool execution ...
```

### 3. Tool Policy Engine (Defense in Depth)

Even after HITL confirmation, a policy engine gates tool execution:

```python
WRITE_TOOLS = {"set_orders_to_teco", "reset_orders_teco", "delete_order"}

class ToolPolicyEngine:
    """
    Modes:
    - permissive: allow all tools (dev/testing)
    - read_only: block all write tools
    - strict: writes only when ENABLE_WRITE_ACTIONS=true
    """
    def __init__(self):
        self.mode = os.getenv("TOOL_POLICY_MODE", "permissive")
        self.enable_writes = os.getenv("ENABLE_WRITE_ACTIONS", "false") == "true"
    
    def evaluate(self, tool_name: str) -> PolicyDecision:
        if tool_name not in WRITE_TOOLS:
            return PolicyDecision(allowed=True)
        if self.mode == "read_only":
            return PolicyDecision(allowed=False, reason="Write disabled (read_only mode)")
        if self.mode == "strict" and not self.enable_writes:
            return PolicyDecision(allowed=False, reason="Write disabled by policy")
        return PolicyDecision(allowed=True)
```

### 4. A2A Response Mapping

Map the `human_input_required` flag to A2A `TaskState.input_required`:

```python
# In the A2A agent executor
if event.get("require_user_input"):
    state = TaskState.input_required   # ← A2A signals UI to show input
elif event.get("is_task_complete"):
    state = TaskState.completed
else:
    state = TaskState.working

await event_queue.enqueue_event(state=state, parts=parts)
```

### 5. Quick Replies for Confirmation

Provide clear confirmation/cancel buttons:

```python
if human_input_required:
    quick_replies = [
        {"title": "Confirm", "value": "confirm"},
        {"title": "Cancel", "value": "cancel"},
    ]
```

## Layer Model

HITL is one layer in a defense-in-depth approach:

| Layer | What It Protects Against | Implementation |
|-------|------------------------|----------------|
| **1. Planner classification** | Misunderstood intent | Planner outputs `goal_type` |
| **2. HITL confirmation** | Unintended writes | Executor HITL gate |
| **3. Tool policy** | Unauthorized writes | `ToolPolicyEngine` |
| **4. API authorization** | Unauthorized system access | SAP user roles / BCR |

HITL (Layer 2) confirms **intent** — "did you really mean to do this?"
API authorization (Layer 4) confirms **permission** — "are you allowed to do this?"

These are complementary, not alternatives.

## Common Mistakes

| Mistake | Why It's Wrong | Fix |
|---------|---------------|-----|
| HITL replaces authorization | User confirms intent, not permissions | Keep both HITL + API auth |
| Confirmation keywords too loose | "yes" in unrelated context triggers write | Use specific patterns: "confirm", "approved" |
| No cancel path | User stuck in confirmation loop | Handle "cancel", "never mind", "no" |
| Write tools enabled by default | Accidents in development | Default `ENABLE_WRITE_ACTIONS=false` |
| No audit log | Can't trace who confirmed what | Log confirmation events with context_id |

## Testing Checklist

- [ ] Write action without confirmation → returns input_required
- [ ] Write action with "confirm" → executes the tool
- [ ] Write action with "cancel" → does NOT execute
- [ ] Tool policy mode `read_only` → blocks all writes regardless of confirmation
- [ ] Tool policy mode `strict` + `ENABLE_WRITE_ACTIONS=false` → blocks writes
- [ ] A2A maps `human_input_required` → `TaskState.input_required`
- [ ] Quick replies show Confirm/Cancel buttons
- [ ] Multiple orders in one TECO request → all listed in confirmation prompt
