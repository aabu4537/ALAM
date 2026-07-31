"""Engine configuration under the two connection modes.

Neither mode fails loudly when wrong. A client-side pool stacked on the
transaction pooler exhausts server slots while appearing idle; prepared
statements against a swapped connection fail intermittently under load and
never in testing. So the choice is asserted directly (ADR-0007).
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import NullPool

from alam.config.settings import Settings
from alam.persistence import session as session_module
from alam.persistence.session import engine_options


@pytest.fixture(autouse=True)
def _reset_engine() -> None:
    session_module.reset_engine()


class TestLocalMode:
    def test_pooler_is_off_by_default(self) -> None:
        """Local development and the always-on loop want a real pool."""
        assert Settings().database_use_transaction_pooler is False

    def test_uses_a_real_pool_with_liveness_checks(self) -> None:
        options = engine_options(Settings())

        assert options["pool_pre_ping"] is True
        assert "poolclass" not in options

    def test_does_not_disable_prepared_statements(self) -> None:
        """Prepared statements are a win on a direct connection; disabling them
        everywhere would be a real cost paid for no reason."""
        assert "connect_args" not in engine_options(Settings())


class TestTransactionPoolerMode:
    @pytest.fixture
    def pooled(self, monkeypatch: pytest.MonkeyPatch) -> Settings:
        monkeypatch.setenv("ALAM_DATABASE_USE_TRANSACTION_POOLER", "true")
        return Settings()

    def test_uses_nullpool(self, pooled: Settings) -> None:
        assert engine_options(pooled)["poolclass"] is NullPool

    def test_disables_prepared_statements(self, pooled: Settings) -> None:
        assert engine_options(pooled)["connect_args"]["prepare_threshold"] is None

    def test_does_not_stack_a_client_side_pool(self, pooled: Settings) -> None:
        assert "pool_pre_ping" not in engine_options(pooled)


class TestEngineLifecycle:
    def test_engine_is_cached(self) -> None:
        assert session_module.get_engine() is session_module.get_engine()

    def test_reset_forces_a_rebuild(self) -> None:
        """Needed because settings changes must be able to take effect."""
        first = session_module.get_engine()
        session_module.reset_engine()

        assert session_module.get_engine() is not first
