# SAP Maintenance Order Agent — A2A Sample

An enterprise-grade A2A agent that queries **SAP S/4HANA Maintenance Order APIs**
to provide plant maintenance insights. Demonstrates the PEOS (Planner→Executor→
Observer→Synthesiser) multi-step architecture with dynamic tool binding, token
optimization, and human-in-the-loop for write operations.

**This is the first SAP / enterprise ERP agent in the A2A samples ecosystem.**

## Architecture

```
User Query
    │
    ▼
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌─────────────┐
│ Planner  │────▶│ Executor │◀───▶│ Observer │────▶│ Synthesiser │
│ (intent  │     │ (tool    │     │ (quality │     │ (format     │
│  + plan) │     │  calls)  │     │  check)  │     │  response)  │
└──────────┘     └──────────┘     └──────────┘     └─────────────┘
                      │  ▲                              │
                      │  │ retry loop (max 10)          │
                      │  │                              ▼
                 SAP S/4HANA               A2A Response (JSON)
                 OData APIs                TextPart + DataPart
```

### PEOS Nodes

| Node | Role | LLM Calls | Token Strategy |
|------|------|-----------|----------------|
| **Planner** | Classifies intent, selects tools, builds execution plan | 1 | 3-turn history window, no tool schemas |
| **Executor** | Calls SAP OData tools, collects results | 1 per iteration | Dynamic tool binding (only plan-relevant tools) |
| **Observer** | Evaluates completeness, detects anomalies | 1 | Truncated result summaries (400 chars/tool) |
| **Synthesiser** | Formats final response with quick replies | 1 | Separate prompt, no tool schemas |

### Token Optimization

| Technique | Savings | How |
|-----------|---------|-----|
| Dynamic tool binding | 60-80% | Executor sees only tools from plan, not all 20 |
| PEOS staged prompts | ~40% | Each node gets a focused system prompt |
| Planner 3-turn window | ~70% per turn | Planner sees only last 3 conversation turns |
| Result truncation | 50KB cap | Large SAP responses capped before LLM sees them |
| History windowing | Bounded | Conversation history capped at 40 messages |

## SAP APIs Used (Public — from SAP API Business Hub)

| API | Entity | Purpose |
|-----|--------|---------|
| [`API_MAINTENANCEORDER`](https://api.sap.com/api/API_MAINTENANCEORDER/overview) v0002 | `MaintenanceOrder`, `MaintenanceOrderOperation`, `MaintOrderOpComponent` | Order header, operations, components |
| [`API_MAINTNOTIFICATION`](https://api.sap.com/api/API_MAINTNOTIFICATION/overview) | `MaintenanceNotification`, `MaintNotificationItem` | Notifications, damage/cause codes |
| [`API_EQUIPMENT`](https://api.sap.com/api/API_EQUIPMENT/overview) | `Equipment` | Equipment master data |
| [`API_FUNCTIONAL_LOCATION`](https://api.sap.com/api/API_FUNCTIONAL_LOCATION/overview) | `FunctionalLocation` | Functional location hierarchy |
| [`API_MATERIAL_STOCK_SRV`](https://api.sap.com/api/API_MATERIAL_STOCK_SRV/overview) | `A_MatlStkInAcctMod` | Stock quantities by plant/storage location |
| [`API_MATERIAL_DOCUMENT_SRV`](https://api.sap.com/api/API_MATERIAL_DOCUMENT_SRV/overview) | `A_MaterialDocumentItem` | Goods movement history |
| [`API_PURCHASEORDER_PROCESS_SRV`](https://api.sap.com/api/API_PURCHASEORDER_PROCESS_SRV/overview) | `A_PurchaseOrder`, `A_PurchaseOrderItem` | Purchase orders linked to maintenance |

## Running

### Prerequisites

- Python 3.12+
- [UV](https://docs.astral.sh/uv/) package manager

### Quick Start

```bash
# Navigate to this sample
cd samples/python/agents/sap_maintenance

# Run the agent (uses mock SAP data by default)
uv run .
```

The agent starts an A2A server on `http://localhost:10020`.

### Test with CLI Host

```bash
# In another terminal
cd samples/python/hosts/cli
uv run . --agent http://localhost:10020
```

### Example Queries

| Query | What Happens |
|-------|-------------|
| `Show high priority orders for plant 1010` | Planner→search tool→Observer→Synthesiser |
| `Get details for order 4000045` | Single order lookup with notifications & long text |
| `Check stock for material 100-100` | Material stock query |
| `Set order 4000045 to TECO` | HITL: asks for confirmation before write |
| `What can you do?` | Returns capability list (zero LLM calls) |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL_NAME` | `gpt-4o` | LLM model (any litellm-compatible) |
| `SAP_BASE_URL` | *(mock mode)* | SAP S/4HANA OData base URL |
| `SAP_USER` | — | SAP system user (basic auth) |
| `SAP_PASSWORD` | — | SAP system password |
| `SAP_CLIENT` | `100` | SAP client number |
| `USE_MOCK_DATA` | `true` | Use built-in mock responses |
| `MAX_EXECUTOR_ITERATIONS` | `10` | Max executor→observer loop iterations |
| `ENABLE_WRITE_ACTIONS` | `false` | Enable TECO/Un-TECO write tools |

### Connecting to a Real SAP System

```bash
export USE_MOCK_DATA=false
export SAP_BASE_URL=https://your-s4hana-system.example.com
export SAP_USER=your_user
export SAP_PASSWORD=your_password
export SAP_CLIENT=100
uv run .
```

## Features Demonstrated

- **A2A Protocol**: AgentCard with skills, streaming, task lifecycle
- **Multi-step tool orchestration**: PEOS graph with conditional routing
- **Dynamic tool binding**: Executor only loads tools referenced in plan
- **Human-in-the-Loop**: Write operations require explicit confirmation
- **Token optimization**: 60-80% reduction via staged prompts + dynamic binding
- **SAP OData integration**: Real API field names, entity relationships, filter patterns
- **Prompt injection protection**: Input sanitization, boundary markers
- **Error masking**: Raw SAP errors never exposed to users
- **Session memory**: Multi-turn context tracking (order IDs, last action)

## Project Structure

```
sap_maintenance/
├── __init__.py
├── __main__.py          # Entry point — starts A2A server
├── agent.py             # PEOS state graph (LangGraph)
├── agent_config.py      # Configuration and constants
├── agent_executor.py    # A2A SDK integration
├── mock_sap_data.py     # Mock SAP OData responses
├── prompts.py           # All LLM prompts (planner, observer, synthesiser)
├── tools.py             # SAP OData tool implementations
├── tool_policy.py       # Write action authorization
├── pyproject.toml       # Dependencies
└── tests/
    └── test_agent.py    # Unit tests
```

## License

Apache-2.0
