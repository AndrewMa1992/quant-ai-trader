"""tests/test_schemas.py – Schema validation tests for v2.1 Pydantic models.

Covers:
- services/model_train_service/api/schemas.py: TrainRequest, TrainJob
- services/risk_service/api/schemas.py: RiskCheckRequest, RiskCheckResult
- services/execution_service/api/schemas.py: OrderRequest, OrderResult
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ═══════════════════════════════════════════════════════════════
# Module A: model_train_service schemas
# ═══════════════════════════════════════════════════════════════

class TestTrainRequest:
    """Tests for TrainRequest schema (from services.model_train_service.api.schemas)."""

    def test_create_full_fields(self):
        """Creating a TrainRequest with all fields should succeed."""
        from services.model_train_service.api.schemas import TrainRequest

        req = TrainRequest(
            model_type="transformer",
            tickers=["AAPL", "MSFT", "GOOGL"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            hyperparams={"learning_rate": 0.001, "batch_size": 128},
        )
        assert req.model_type == "transformer"
        assert req.tickers == ["AAPL", "MSFT", "GOOGL"]
        assert req.start_date == "2024-01-01"
        assert req.end_date == "2024-12-31"
        assert req.hyperparams == {"learning_rate": 0.001, "batch_size": 128}

    def test_create_minimal_fields(self):
        """Creating a TrainRequest with only required fields should succeed."""
        from services.model_train_service.api.schemas import TrainRequest

        req = TrainRequest(
            model_type="rl_agent",
            tickers=["NVDA"],
            start_date="2023-06-01",
            end_date="2024-06-01",
        )
        assert req.model_type == "rl_agent"
        assert req.tickers == ["NVDA"]
        assert req.hyperparams is None

    def test_missing_required_raises(self):
        """Missing required fields should raise ValidationError."""
        from services.model_train_service.api.schemas import TrainRequest

        with pytest.raises(ValidationError):
            TrainRequest()

        with pytest.raises(ValidationError):
            TrainRequest(model_type="transformer")

        with pytest.raises(ValidationError):
            TrainRequest(model_type="transformer", tickers=["AAPL"])

    def test_invalid_type_tickers(self):
        """tickers must be a list of strings."""
        from services.model_train_service.api.schemas import TrainRequest

        with pytest.raises(ValidationError):
            TrainRequest(
                model_type="transformer",
                tickers="AAPL",  # string, not list
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_empty_tickers_raises(self):
        """tickers with min_length=1 should reject empty list."""
        from services.model_train_service.api.schemas import TrainRequest

        with pytest.raises(ValidationError):
            TrainRequest(
                model_type="transformer",
                tickers=[],
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_invalid_model_type(self):
        """Any string is accepted since model_type is just str (no enum validation in schema)."""
        from services.model_train_service.api.schemas import TrainRequest

        req = TrainRequest(
            model_type="garbage_model",
            tickers=["AAPL"],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert req.model_type == "garbage_model"

    def test_serialize_model_dump(self):
        """model_dump() should produce correct dict."""
        from services.model_train_service.api.schemas import TrainRequest

        req = TrainRequest(
            model_type="transformer",
            tickers=["AAPL", "MSFT"],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        dumped = req.model_dump()
        assert dumped["model_type"] == "transformer"
        assert dumped["tickers"] == ["AAPL", "MSFT"]
        assert dumped["hyperparams"] is None

    def test_deserialize_model_validate(self):
        """model_validate() should reconstruct from dict."""
        from services.model_train_service.api.schemas import TrainRequest

        data = {
            "model_type": "rl_agent",
            "tickers": ["TSLA"],
            "start_date": "2024-06-01",
            "end_date": "2024-12-31",
            "hyperparams": {"gamma": 0.99},
        }
        req = TrainRequest.model_validate(data)
        assert req.model_type == "rl_agent"
        assert req.hyperparams == {"gamma": 0.99}

    def test_hyperparams_optional(self):
        """hyperparams defaults to None when not provided."""
        from services.model_train_service.api.schemas import TrainRequest

        req = TrainRequest(
            model_type="transformer",
            tickers=["AAPL"],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert req.hyperparams is None


class TestTrainJob:
    """Tests for TrainJob schema (from services.model_train_service.api.schemas)."""

    def test_create_full_fields(self):
        from services.model_train_service.api.schemas import TrainJob

        job = TrainJob(
            job_id="uuid-1234",
            model_type="transformer",
            status="completed",
            metrics={"loss": 0.05, "sharpe": 1.8},
            mlflow_run_id="run-5678",
            model_version=3,
            created_at=1700000000.0,
            completed_at=1700003600.0,
        )
        assert job.job_id == "uuid-1234"
        assert job.status == "completed"
        assert job.metrics == {"loss": 0.05, "sharpe": 1.8}
        assert job.mlflow_run_id == "run-5678"
        assert job.model_version == 3

    def test_create_minimal_fields(self):
        from services.model_train_service.api.schemas import TrainJob

        job = TrainJob(
            job_id="uuid-min",
            model_type="rl_agent",
            status="queued",
            created_at=1700000000.0,
        )
        assert job.job_id == "uuid-min"
        assert job.metrics is None
        assert job.error is None
        assert job.mlflow_run_id is None
        assert job.model_version is None
        assert job.completed_at is None

    def test_missing_required_raises(self):
        from services.model_train_service.api.schemas import TrainJob

        with pytest.raises(ValidationError):
            TrainJob()

        with pytest.raises(ValidationError):
            TrainJob(job_id="x")

    def test_model_dump_and_validate(self):
        from services.model_train_service.api.schemas import TrainJob

        job = TrainJob(
            job_id="uuid-test",
            model_type="transformer",
            status="running",
            created_at=1700000000.0,
            error="CUDA OOM",
        )
        data = job.model_dump()
        restored = TrainJob.model_validate(data)
        assert restored.job_id == "uuid-test"
        assert restored.error == "CUDA OOM"
        assert restored.completed_at is None


# ═══════════════════════════════════════════════════════════════
# Module A: risk_service schemas
# ═══════════════════════════════════════════════════════════════

class TestRiskCheckRequest:
    """Tests for RiskCheckRequest schema (from services.risk_service.api.schemas)."""

    def test_create_full_fields(self):
        from services.risk_service.api.schemas import RiskCheckRequest

        req = RiskCheckRequest(
            ticker="AAPL",
            quantity=100,
            price=150.0,
            portfolio_state={"nav": 1_000_000.0, "positions": {"AAPL": 50}},
            signal_strength=0.75,
        )
        assert req.ticker == "AAPL"
        assert req.quantity == 100
        assert req.price == 150.0
        assert req.signal_strength == 0.75
        assert req.portfolio_state == {"nav": 1_000_000.0, "positions": {"AAPL": 50}}

    def test_create_minimal_fields(self):
        from services.risk_service.api.schemas import RiskCheckRequest

        req = RiskCheckRequest(ticker="MSFT", quantity=50, price=300.0)
        assert req.ticker == "MSFT"
        assert req.quantity == 50
        assert req.price == 300.0
        assert req.portfolio_state is None
        assert req.signal_strength is None

    def test_quantity_gt_zero(self):
        """quantity must be > 0."""
        from services.risk_service.api.schemas import RiskCheckRequest

        with pytest.raises(ValidationError):
            RiskCheckRequest(ticker="AAPL", quantity=0, price=150.0)

        with pytest.raises(ValidationError):
            RiskCheckRequest(ticker="AAPL", quantity=-5, price=150.0)

    def test_price_gt_zero(self):
        """price must be > 0."""
        from services.risk_service.api.schemas import RiskCheckRequest

        with pytest.raises(ValidationError):
            RiskCheckRequest(ticker="AAPL", quantity=100, price=0.0)

        with pytest.raises(ValidationError):
            RiskCheckRequest(ticker="AAPL", quantity=100, price=-10.0)

    def test_signal_strength_range(self):
        """signal_strength must be in [-1.0, 1.0]."""
        from services.risk_service.api.schemas import RiskCheckRequest

        # Valid at extremes
        req1 = RiskCheckRequest(ticker="AAPL", quantity=100, price=150.0, signal_strength=1.0)
        assert req1.signal_strength == 1.0

        req2 = RiskCheckRequest(ticker="AAPL", quantity=100, price=150.0, signal_strength=-1.0)
        assert req2.signal_strength == -1.0

        # Out of range should fail
        with pytest.raises(ValidationError):
            RiskCheckRequest(ticker="AAPL", quantity=100, price=150.0, signal_strength=1.1)

        with pytest.raises(ValidationError):
            RiskCheckRequest(ticker="AAPL", quantity=100, price=150.0, signal_strength=-1.1)

    def test_missing_required_raises(self):
        from services.risk_service.api.schemas import RiskCheckRequest

        with pytest.raises(ValidationError):
            RiskCheckRequest()

        with pytest.raises(ValidationError):
            RiskCheckRequest(ticker="AAPL")

    def test_model_dump_model_validate(self):
        from services.risk_service.api.schemas import RiskCheckRequest

        req = RiskCheckRequest(
            ticker="GOOGL",
            quantity=200,
            price=140.0,
            signal_strength=-0.5,
        )
        data = req.model_dump()
        restored = RiskCheckRequest.model_validate(data)
        assert restored.ticker == "GOOGL"
        assert restored.quantity == 200
        assert restored.signal_strength == -0.5


class TestRiskCheckResult:
    """Tests for RiskCheckResult schema."""

    def test_create_full_fields(self):
        from services.risk_service.api.schemas import RiskCheckResult

        result = RiskCheckResult(
            passed=True,
            reason="All checks passed",
            warnings=["Portfolio concentration approaching limit"],
            sanitized_weights={"AAPL": 0.15, "MSFT": 0.10},
        )
        assert result.passed is True
        assert result.reason == "All checks passed"
        assert len(result.warnings) == 1
        assert result.sanitized_weights == {"AAPL": 0.15, "MSFT": 0.10}

    def test_create_minimal_fields(self):
        from services.risk_service.api.schemas import RiskCheckResult

        result = RiskCheckResult(passed=False, reason="VaR limit exceeded")
        assert result.passed is False
        assert result.warnings == []
        assert result.sanitized_weights is None

    def test_warnings_default_factory(self):
        """warnings should default to empty list, not shared across instances."""
        from services.risk_service.api.schemas import RiskCheckResult

        r1 = RiskCheckResult(passed=True, reason="ok")
        r2 = RiskCheckResult(passed=True, reason="also ok", warnings=["warning 1"])
        assert r1.warnings == []
        assert r2.warnings == ["warning 1"]

    def test_model_dump_model_validate(self):
        from services.risk_service.api.schemas import RiskCheckResult

        result = RiskCheckResult(
            passed=True,
            reason="Pass",
            warnings=["w1", "w2"],
        )
        data = result.model_dump()
        restored = RiskCheckResult.model_validate(data)
        assert restored.passed is True
        assert restored.warnings == ["w1", "w2"]


# ═══════════════════════════════════════════════════════════════
# Module A: execution_service schemas
# ═══════════════════════════════════════════════════════════════

class TestOrderRequest:
    """Tests for OrderRequest schema (from services.execution_service.api.schemas)."""

    def test_create_full_fields(self):
        from services.execution_service.api.schemas import OrderRequest

        req = OrderRequest(
            ticker="AAPL",
            side="BUY",
            quantity=100,
            order_type="LMT",
            limit_price=150.0,
            algo="twap",
            account="acct-123",
        )
        assert req.ticker == "AAPL"
        assert req.side == "BUY"
        assert req.quantity == 100
        assert req.order_type == "LMT"
        assert req.limit_price == 150.0
        assert req.algo == "twap"
        assert req.account == "acct-123"

    def test_create_minimal_fields(self):
        from services.execution_service.api.schemas import OrderRequest

        req = OrderRequest(ticker="MSFT", side="SELL", quantity=50)
        assert req.ticker == "MSFT"
        assert req.side == "SELL"
        assert req.quantity == 50
        assert req.order_type == "MKT"  # default
        assert req.limit_price is None
        assert req.algo is None
        assert req.account is None

    def test_side_pattern_valid(self):
        """side must be BUY or SELL exactly."""
        from services.execution_service.api.schemas import OrderRequest

        # Valid
        OrderRequest(ticker="AAPL", side="BUY", quantity=10)
        OrderRequest(ticker="AAPL", side="SELL", quantity=10)

    def test_side_pattern_invalid(self):
        """Invalid side values should raise ValidationError."""
        from services.execution_service.api.schemas import OrderRequest

        for bad_side in ["buy", "sell", "HOLD", "Buy", "", "BUY_SELL"]:
            with pytest.raises(ValidationError):
                OrderRequest(ticker="AAPL", side=bad_side, quantity=10)

    def test_order_type_pattern_invalid(self):
        """Invalid order_type should raise ValidationError."""
        from services.execution_service.api.schemas import OrderRequest

        with pytest.raises(ValidationError):
            OrderRequest(ticker="AAPL", side="BUY", quantity=10, order_type="STOP")

        # Valid
        req = OrderRequest(ticker="AAPL", side="BUY", quantity=10, order_type="LMT")
        assert req.order_type == "LMT"

    def test_quantity_gt_zero(self):
        from services.execution_service.api.schemas import OrderRequest

        with pytest.raises(ValidationError):
            OrderRequest(ticker="AAPL", side="BUY", quantity=0)

        with pytest.raises(ValidationError):
            OrderRequest(ticker="AAPL", side="BUY", quantity=-10)

    def test_limit_price_gt_zero(self):
        from services.execution_service.api.schemas import OrderRequest

        with pytest.raises(ValidationError):
            OrderRequest(ticker="AAPL", side="BUY", quantity=10, limit_price=-5.0)

        with pytest.raises(ValidationError):
            OrderRequest(ticker="AAPL", side="BUY", quantity=10, limit_price=0.0)

    def test_model_dump_model_validate(self):
        from services.execution_service.api.schemas import OrderRequest

        req = OrderRequest(
            ticker="TSLA",
            side="BUY",
            quantity=200,
            order_type="LMT",
            limit_price=250.0,
            algo="vwap",
        )
        data = req.model_dump()
        restored = OrderRequest.model_validate(data)
        assert restored.side == "BUY"
        assert restored.order_type == "LMT"
        assert restored.limit_price == 250.0
        assert restored.algo == "vwap"


class TestOrderResult:
    """Tests for OrderResult schema."""

    def test_create_full_fields(self):
        from services.execution_service.api.schemas import OrderResult

        result = OrderResult(
            order_id="uuid-order-1",
            ticker="AAPL",
            side="BUY",
            quantity=100,
            filled_price=152.30,
            filled_qty=75.0,
            status="partial_fill",
            algo="twap",
            placed_at=1700000000.0,
            updated_at=1700000100.0,
        )
        assert result.order_id == "uuid-order-1"
        assert result.status == "partial_fill"
        assert result.filled_price == 152.30
        assert result.filled_qty == 75.0

    def test_create_minimal_fields(self):
        from services.execution_service.api.schemas import OrderResult

        result = OrderResult(
            order_id="uuid-min",
            ticker="MSFT",
            side="SELL",
            quantity=50,
            status="queued",
            placed_at=1700000000.0,
        )
        assert result.order_id == "uuid-min"
        assert result.filled_price is None
        assert result.filled_qty == 0.0  # default
        assert result.algo is None
        assert result.updated_at is None

    def test_model_dump_model_validate(self):
        from services.execution_service.api.schemas import OrderResult

        result = OrderResult(
            order_id="uuid-test",
            ticker="GOOGL",
            side="BUY",
            quantity=30,
            status="filled",
            filled_price=140.0,
            filled_qty=30.0,
            placed_at=1700000000.0,
            updated_at=1700000100.0,
        )
        data = result.model_dump()
        restored = OrderResult.model_validate(data)
        assert restored.status == "filled"
        assert restored.filled_qty == 30.0
