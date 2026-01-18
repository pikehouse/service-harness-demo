"""Agent process for working tickets autonomously."""

from harness.agent.tools import AgentToolkit
from harness.agent.runner import AgentRunner

__all__ = ["AgentToolkit", "AgentRunner", "run_agent"]


def run_agent():
    """Run the agent process."""
    print("Starting agent process", flush=True)
    runner = AgentRunner()
    runner.run()
