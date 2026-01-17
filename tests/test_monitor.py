"""Tests for the monitor module (SLO and invariant evaluation)."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harness.database import Base
from harness.models import SLO, Invariant, Ticket, TicketStatus, TicketSourceType
from harness.grafana import PrometheusClient
from harness.monitor.slo_evaluator import SLOEvaluator, SLOEvaluation
from harness.monitor.invariant_evaluator import InvariantEvaluator, InvariantEvaluation, parse_condition
from harness.monitor.runner import MonitorRunner


@pytest.fixture
def db_session():
    """Create an in-memory database session for testing."""
    from harness import models  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def mock_prometheus():
    """Create a mock Prometheus client."""
    client = MagicMock(spec=PrometheusClient)
    client.get_metric_value = MagicMock(return_value=0.999)
    return client


class TestParseCondition:
    """Tests for the condition parser."""

    def test_parse_greater_than(self):
        op_func, threshold = parse_condition("> 20")
        assert threshold == 20.0
        assert op_func(25, 20) is True
        assert op_func(15, 20) is False

    def test_parse_greater_equal(self):
        op_func, threshold = parse_condition(">= 20")
        assert threshold == 20.0
        assert op_func(20, 20) is True
        assert op_func(19, 20) is False

    def test_parse_less_than(self):
        op_func, threshold = parse_condition("< 100")
        assert threshold == 100.0
        assert op_func(50, 100) is True
        assert op_func(150, 100) is False

    def test_parse_less_equal(self):
        op_func, threshold = parse_condition("<= 100")
        assert threshold == 100.0
        assert op_func(100, 100) is True
        assert op_func(101, 100) is False

    def test_parse_equal(self):
        op_func, threshold = parse_condition("== 0")
        assert threshold == 0.0
        assert op_func(0, 0) is True
        assert op_func(1, 0) is False

    def test_parse_not_equal(self):
        op_func, threshold = parse_condition("!= 0")
        assert threshold == 0.0
        assert op_func(1, 0) is True
        assert op_func(0, 0) is False

    def test_parse_with_decimal(self):
        op_func, threshold = parse_condition("> 0.5")
        assert threshold == 0.5
        assert op_func(0.6, 0.5) is True

    def test_parse_with_negative(self):
        op_func, threshold = parse_condition("> -10")
        assert threshold == -10.0
        assert op_func(0, -10) is True

    def test_parse_with_spaces(self):
        op_func, threshold = parse_condition("  >   20  ")
        assert threshold == 20.0

    def test_parse_invalid_format(self):
        with pytest.raises(ValueError):
            parse_condition("invalid")

    def test_parse_missing_operator(self):
        with pytest.raises(ValueError):
            parse_condition("20")


class TestSLOEvaluator:
    """Tests for the SLO evaluator."""

    def test_evaluate_slo_success(self, mock_prometheus):
        """Test evaluating an SLO that's within target."""
        mock_prometheus.get_metric_value.return_value = 0.9995  # 99.95% success rate

        slo = SLO(
            id=1,
            name="availability",
            target=0.999,
            window_days=30,
            metric_query='sum(rate(success[5m])) / sum(rate(total[5m]))',
        )

        evaluator = SLOEvaluator(prometheus_client=mock_prometheus)
        result = evaluator.evaluate(slo)

        assert result.slo_id == 1
        assert result.slo_name == "availability"
        assert result.current_value == 0.9995
        assert result.error is None

    def test_evaluate_slo_no_data(self, mock_prometheus):
        """Test evaluating an SLO when no data is returned."""
        mock_prometheus.get_metric_value.return_value = None

        slo = SLO(
            id=1,
            name="availability",
            target=0.999,
            window_days=30,
            metric_query='sum(rate(success[5m])) / sum(rate(total[5m]))',
        )

        evaluator = SLOEvaluator(prometheus_client=mock_prometheus)
        result = evaluator.evaluate(slo)

        assert result.current_value is None
        assert result.is_violating is False
        assert "No data" in result.error

    def test_evaluate_slo_error(self, mock_prometheus):
        """Test evaluating an SLO when Prometheus raises an error."""
        mock_prometheus.get_metric_value.side_effect = Exception("Connection error")

        slo = SLO(
            id=1,
            name="availability",
            target=0.999,
            window_days=30,
            metric_query='sum(rate(success[5m])) / sum(rate(total[5m]))',
        )

        evaluator = SLOEvaluator(prometheus_client=mock_prometheus)
        result = evaluator.evaluate(slo)

        assert result.is_violating is False
        assert "Connection error" in result.error

    def test_create_violation_ticket(self, db_session, mock_prometheus):
        """Test creating a ticket for an SLO violation."""
        slo = SLO(
            name="availability",
            target=0.999,
            window_days=30,
            metric_query='query',
            enabled=True,
        )
        db_session.add(slo)
        db_session.commit()

        evaluation = SLOEvaluation(
            slo_id=slo.id,
            slo_name=slo.name,
            target=0.999,
            current_value=0.98,
            error_budget_remaining=0,
            burn_rate=15.0,
            is_violating=True,
            violation_severity="fast",
            evaluated_at=datetime.utcnow(),
        )

        evaluator = SLOEvaluator(prometheus_client=mock_prometheus)
        ticket = evaluator.create_violation_ticket(db_session, evaluation)

        assert ticket is not None
        assert ticket.source_type == TicketSourceType.SLO_VIOLATION
        assert ticket.source_id == str(slo.id)
        assert "availability" in ticket.objective

    def test_no_duplicate_violation_ticket(self, db_session, mock_prometheus):
        """Test that duplicate tickets aren't created for the same SLO."""
        slo = SLO(
            name="availability",
            target=0.999,
            window_days=30,
            metric_query='query',
            enabled=True,
        )
        db_session.add(slo)
        db_session.commit()

        evaluation = SLOEvaluation(
            slo_id=slo.id,
            slo_name=slo.name,
            target=0.999,
            current_value=0.98,
            error_budget_remaining=0,
            burn_rate=15.0,
            is_violating=True,
            violation_severity="fast",
            evaluated_at=datetime.utcnow(),
        )

        evaluator = SLOEvaluator(prometheus_client=mock_prometheus)

        # First ticket should be created
        ticket1 = evaluator.create_violation_ticket(db_session, evaluation)
        assert ticket1 is not None

        # Second ticket should not be created
        ticket2 = evaluator.create_violation_ticket(db_session, evaluation)
        assert ticket2 is None


class TestInvariantEvaluator:
    """Tests for the invariant evaluator."""

    def test_evaluate_invariant_passing(self, mock_prometheus):
        """Test evaluating an invariant that passes."""
        mock_prometheus.get_metric_value.return_value = 25.0  # > 20

        invariant = Invariant(
            id=1,
            name="capacity_headroom",
            query="capacity_percent",
            condition="> 20",
        )

        evaluator = InvariantEvaluator(prometheus_client=mock_prometheus)
        result = evaluator.evaluate(invariant)

        assert result.invariant_id == 1
        assert result.is_passing is True
        assert result.current_value == 25.0
        assert result.threshold_value == 20.0

    def test_evaluate_invariant_failing(self, mock_prometheus):
        """Test evaluating an invariant that fails."""
        mock_prometheus.get_metric_value.return_value = 15.0  # < 20

        invariant = Invariant(
            id=1,
            name="capacity_headroom",
            query="capacity_percent",
            condition="> 20",
        )

        evaluator = InvariantEvaluator(prometheus_client=mock_prometheus)
        result = evaluator.evaluate(invariant)

        assert result.is_passing is False
        assert result.current_value == 15.0

    def test_evaluate_invariant_no_data(self, mock_prometheus):
        """Test evaluating an invariant when no data is returned."""
        mock_prometheus.get_metric_value.return_value = None

        invariant = Invariant(
            id=1,
            name="capacity_headroom",
            query="capacity_percent",
            condition="> 20",
        )

        evaluator = InvariantEvaluator(prometheus_client=mock_prometheus)
        result = evaluator.evaluate(invariant)

        assert result.is_passing is True  # No data = assume passing
        assert "No data" in result.error

    def test_evaluate_invariant_invalid_condition(self, mock_prometheus):
        """Test evaluating an invariant with an invalid condition."""
        invariant = Invariant(
            id=1,
            name="invalid",
            query="query",
            condition="invalid_condition",
        )

        evaluator = InvariantEvaluator(prometheus_client=mock_prometheus)
        result = evaluator.evaluate(invariant)

        assert result.is_passing is True  # Invalid condition = assume passing
        assert "Invalid condition" in result.error

    def test_create_violation_ticket(self, db_session, mock_prometheus):
        """Test creating a ticket for an invariant violation."""
        invariant = Invariant(
            name="capacity_headroom",
            query="capacity_percent",
            condition="> 20",
            enabled=True,
        )
        db_session.add(invariant)
        db_session.commit()

        evaluation = InvariantEvaluation(
            invariant_id=invariant.id,
            invariant_name=invariant.name,
            query=invariant.query,
            condition=invariant.condition,
            current_value=15.0,
            threshold_value=20.0,
            is_passing=False,
            evaluated_at=datetime.utcnow(),
        )

        evaluator = InvariantEvaluator(prometheus_client=mock_prometheus)
        ticket = evaluator.create_violation_ticket(db_session, evaluation)

        assert ticket is not None
        assert ticket.source_type == TicketSourceType.INVARIANT_VIOLATION
        assert ticket.source_id == str(invariant.id)
        assert "capacity_headroom" in ticket.objective

    def test_no_duplicate_violation_ticket(self, db_session, mock_prometheus):
        """Test that duplicate tickets aren't created for the same invariant."""
        invariant = Invariant(
            name="capacity_headroom",
            query="capacity_percent",
            condition="> 20",
            enabled=True,
        )
        db_session.add(invariant)
        db_session.commit()

        evaluation = InvariantEvaluation(
            invariant_id=invariant.id,
            invariant_name=invariant.name,
            query=invariant.query,
            condition=invariant.condition,
            current_value=15.0,
            threshold_value=20.0,
            is_passing=False,
            evaluated_at=datetime.utcnow(),
        )

        evaluator = InvariantEvaluator(prometheus_client=mock_prometheus)

        # First ticket should be created
        ticket1 = evaluator.create_violation_ticket(db_session, evaluation)
        assert ticket1 is not None

        # Second ticket should not be created
        ticket2 = evaluator.create_violation_ticket(db_session, evaluation)
        assert ticket2 is None


class TestMonitorRunner:
    """Tests for the monitor runner."""

    def test_run_once(self, db_session, mock_prometheus):
        """Test running a single evaluation cycle."""
        # Add an SLO and invariant
        slo = SLO(
            name="availability",
            target=0.999,
            window_days=30,
            metric_query='query',
            enabled=True,
        )
        invariant = Invariant(
            name="capacity",
            query="capacity_percent",
            condition="> 20",
            enabled=True,
        )
        db_session.add_all([slo, invariant])
        db_session.commit()

        # Mock prometheus to return values that pass
        mock_prometheus.get_metric_value.return_value = 0.9995

        # Create a session factory that returns our test session
        def session_factory():
            return db_session

        runner = MonitorRunner(
            prometheus_client=mock_prometheus,
            session_factory=session_factory,
        )

        results = runner.run_once()

        assert len(results["slo_evaluations"]) == 1
        assert len(results["invariant_evaluations"]) == 1
        assert len(results["errors"]) == 0

    def test_run_once_creates_tickets_for_violations(self, db_session, mock_prometheus):
        """Test that run_once creates tickets for violations."""
        invariant = Invariant(
            name="capacity",
            query="capacity_percent",
            condition="> 20",
            enabled=True,
        )
        db_session.add(invariant)
        db_session.commit()

        # Mock prometheus to return a failing value
        mock_prometheus.get_metric_value.return_value = 15.0  # Fails > 20

        def session_factory():
            return db_session

        runner = MonitorRunner(
            prometheus_client=mock_prometheus,
            session_factory=session_factory,
        )

        results = runner.run_once()

        # Should have created a ticket
        assert len(results["tickets_created"]) == 1
        assert results["tickets_created"][0]["type"] == "invariant_violation"

        # Verify ticket in database
        tickets = db_session.query(Ticket).all()
        assert len(tickets) == 1
        assert tickets[0].source_type == TicketSourceType.INVARIANT_VIOLATION

    def test_status(self, mock_prometheus):
        """Test getting monitor status."""
        runner = MonitorRunner(prometheus_client=mock_prometheus)

        status = runner.status
        assert status["running"] is False
        assert status["slo_interval_seconds"] == 60
        assert status["invariant_interval_seconds"] == 60
