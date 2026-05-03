<div align="center">

# 🤖 A2A SAP Agent

**Enterprise SAP Maintenance Agent for the [Agent2Agent (A2A) Protocol](https://a2a-protocol.org/)**

[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v1.0-blue?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyQzYuNSAyIDIgNi41IDIgMTJzNC41IDEwIDEwIDEwIDEwLTQuNSAxMC0xMFMxNy41IDIgMTIgMnptMCAxOGMtNC40IDAtOC0zLjYtOC04czMuNi04IDgtOCA4IDMuNiA4IDgtMy42IDgtOCA4eiIvPjwvc3ZnPg==)](https://a2a-protocol.org/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-🦜🕸️-1C3C3C?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-Apache_2.0-green?style=for-the-badge&logo=apache)](LICENSE)

[![SAP S/4HANA](https://img.shields.io/badge/SAP-S%2F4HANA-0FAAFF?style=flat-square&logo=sap&logoColor=white)](https://api.sap.com/)
[![LiteLLM](https://img.shields.io/badge/LiteLLM-Multi--Provider-FF6B35?style=flat-square)](https://docs.litellm.ai/)
[![Mock Data](https://img.shields.io/badge/Mock_Data-Included-success?style=flat-square)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](https://github.com/naveenkumarbaskaran/a2a-sap-agent/pulls)

<br>

*The first enterprise ERP agent sample for the A2A ecosystem — queries SAP S/4HANA Plant Maintenance APIs using a production-grade PEOS (Planner→Executor→Observer→Synthesiser) architecture.*

</div>

---

## 🏗️ Architecture

```
User ──► A2A Server ──► Planner ──► Executor (loop) ──► Observer ──► Synthesiser ──► Response
                           │            │
                           │       Tool Calls (11 SAP OData tools)
                           │
                     Dynamic Tool Binding
                     (only relevant tools per query)
```

**PEOS State Machine** — 4-node LangGraph graph with retry loop, dynamic tool selection, and token-optimized prompts.

## 📦 What's Inside

| # | Component | Path | Description |
|:---:|-----------|------|-------------|
| 🔧 | **SAP Maintenance Agent** | [`samples/python/agents/sap_maintenance/`](samples/python/agents/sap_maintenance/) | Full A2A agent with 11 SAP OData tools, mock data, and PEOS graph |
| 🧩 | **PEOS Pattern Library** | [`patterns/peos/`](patterns/peos/) | Framework-agnostic reference implementation of the PEOS pattern |
| 📊 | **Token Optimization Guide** | [`guides/token-optimization.md`](guides/token-optimization.md) | 5 battle-tested techniques saving 60-80% tokens |
| 🛡️ | **HITL Write Safety** | [`guides/hitl-write-safety.md`](guides/hitl-write-safety.md) | Human-in-the-loop pattern for destructive operations |

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/naveenkumarbaskaran/a2a-sap-agent.git
cd a2a-sap-agent/samples/python/agents/sap_maintenance

# Install
pip install -e .

# Run (mock mode — no SAP system needed)
python -m app

# Agent runs on http://localhost:10020
# Agent Card at http://localhost:10020/.well-known/agent.json
```

## 🛠️ SAP Tools (11 OData Tools)

| Tool | SAP API | Description |
|------|---------|-------------|
| `search_maintenance_orders` | `API_MAINTENANCEORDER` | Search with 12+ filter dimensions |
| `get_maintenance_order` | `API_MAINTENANCEORDER` | Full order detail with operations |
| `get_order_costs` | `API_MAINTENANCEORDER` | Cost breakdown by category |
| `get_confirmations` | `API_MAINTENANCEORDER` | Time confirmations and progress |
| `get_equipment_details` | `API_EQUIPMENT` | Equipment master data |
| `get_functional_location` | `API_FUNCTLOCATION` | Functional location hierarchy |
| `get_material_stock` | `API_MATERIAL_STOCK` | Plant-level stock availability |
| `get_notifications` | `API_MAINTNOTIFICATION` | Maintenance notifications |
| `search_purchase_orders` | `API_PURCHASEORDER` | Related procurement docs |
| `technically_complete_order` | `API_MAINTENANCEORDER` | TECO with HITL confirmation |
| `reverse_teco` | `API_MAINTENANCEORDER` | Reverse TECO with HITL |

> All APIs are publicly documented on [SAP API Business Hub](https://api.sap.com/). Mock data is included — no SAP system required to run.

## 🔑 Key Principles

- **Zero PII** — No credentials, hostnames, or internal references
- **Public SAP APIs only** — All from [api.sap.com](https://api.sap.com/)
- **Any LLM provider** — Uses LiteLLM (OpenAI, Anthropic, Google, Azure, local)
- **Production patterns** — Extracted from agents deployed on Kubernetes
- **Mock-first** — Runs completely offline with realistic sample data

## 🤝 Contributing

PRs welcome! This repo also serves as staging for contributions to [`a2aproject/a2a-samples`](https://github.com/a2aproject/a2a-samples).

## 📄 License

[Apache-2.0](LICENSE) — consistent with the A2A project.
