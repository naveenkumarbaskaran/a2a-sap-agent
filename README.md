# A2A Protocol Contributions

Open-source contributions to the [Agent2Agent (A2A) Protocol](https://github.com/a2aproject) ecosystem.

## Contributions

| # | Contribution | Target | Description |
|---|-------------|--------|-------------|
| 1 | [SAP Maintenance Agent Sample](samples/python/agents/sap_maintenance/) | PR → `a2a-samples` | First enterprise ERP agent in A2A samples — queries SAP S/4HANA Maintenance Order APIs using PEOS architecture |
| 2 | [PEOS Pattern Library](patterns/peos/) | Standalone reference | Planner→Executor→Observer→Synthesiser pattern with LangGraph — production-grade multi-step agent architecture |
| 3 | [Token Optimization Guide](guides/token-optimization.md) | Docs contribution | Battle-tested techniques saving 60-80% tokens in multi-step agents |
| 4 | [HITL Write Safety Pattern](guides/hitl-write-safety.md) | Docs / sample | Human-in-the-loop confirmation flow for agents performing write operations |

## Key Principles

- **No PII or credentials** — All samples use mock data and placeholder configurations
- **Public SAP APIs only** — References standard APIs from [SAP API Business Hub](https://api.sap.com/)
- **Framework-agnostic patterns** — PEOS architecture works with any LLM provider
- **Production-tested** — Patterns extracted from agents deployed on Kubernetes with real enterprise workloads

## License

Apache-2.0 — consistent with the A2A project.
