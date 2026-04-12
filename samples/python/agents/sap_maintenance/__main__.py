"""Entry point — starts the SAP Maintenance Order Agent as an A2A server."""

import logging
import click

from a2a.server.apps.starlette import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_executor import SAPMaintenanceAgentExecutor


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_agent_card(host: str, port: int) -> AgentCard:
    """Build the A2A Agent Card describing this agent's capabilities."""
    return AgentCard(
        name="SAP Maintenance Order Analyst",
        description=(
            "Analyzes SAP S/4HANA maintenance orders — search orders, check confirmations, "
            "view costs, inspect equipment, and manage TECO status. Uses the PEOS "
            "(Planner→Executor→Observer→Synthesiser) architecture with dynamic tool binding "
            "for token-efficient multi-step analysis."
        ),
        url=f"http://{host}:{port}/",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
        skills=[
            AgentSkill(
                id="sap_maintenance_analysis",
                name="SAP Maintenance Order Analysis",
                description=(
                    "Search and analyze SAP S/4HANA maintenance orders. "
                    "Supports order lookup, cost breakdown, confirmation status, "
                    "material stock checks, equipment details, and TECO management."
                ),
                tags=["sap", "maintenance", "erp", "s4hana", "plant-maintenance"],
                examples=[
                    "Show high priority orders for plant 1010",
                    "Get details for order 4000045",
                    "Check stock for material 100-100",
                    "Which orders are ready for TECO?",
                    "Cost breakdown for order 4000045",
                ],
            ),
        ],
    )


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=10020, type=int, help="Port to listen on")
def main(host: str, port: int):
    """Start the SAP Maintenance Order Agent A2A server."""
    agent_card = build_agent_card(host, port)
    executor = SAPMaintenanceAgentExecutor()
    handler = DefaultRequestHandler(agent_executor=executor, task_store=None)
    app = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)

    logger.info("Starting SAP Maintenance Agent on %s:%d", host, port)
    logger.info("Agent Card: %s", agent_card.name)
    logger.info("Mock mode: %s", "enabled" if __import__("agent_config").USE_MOCK_DATA else "disabled")

    import uvicorn
    uvicorn.run(app.build(), host=host, port=port)


if __name__ == "__main__":
    main()
