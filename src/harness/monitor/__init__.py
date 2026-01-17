"""Monitor process for evaluating SLOs and invariants."""

from harness.monitor.slo_evaluator import SLOEvaluator
from harness.monitor.invariant_evaluator import InvariantEvaluator
from harness.monitor.runner import MonitorRunner

__all__ = ["SLOEvaluator", "InvariantEvaluator", "MonitorRunner", "run_monitor"]


def run_monitor():
    """Run the monitor process."""
    from harness.monitor.scheduler import MonitorScheduler
    print("Starting monitor process")
    scheduler = MonitorScheduler()
    scheduler.run()
