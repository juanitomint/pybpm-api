"""Signal Service — persistent global event storage and lookup.

Signals are thrown by an EndSignalEvent (or IntermediateSignalEventThrowing)
and persist in the database so any matching catcher can discover them later,
enabling cross-case / cross-model signal communication.
"""

from __future__ import annotations

import logging

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal import Signal

logger = logging.getLogger(__name__)


class SignalService:
    """Persistent signal storage and lookup for global signal events."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def throw_signal(
        self, name: str, idwf: str, case_id: str | None = None, data: dict | None = None
    ) -> Signal:
        """Persist a signal throw for catcher matching.

        Args:
            name: Signal name (matches shape.properties.name on throwing/catching shapes).
            idwf: Workflow ID that threw the signal.
            case_id: Optional case context; global signals have no case context.
            data: Optional payload attached to the signal throw.

        Returns:
            The created ``Signal`` row.
        """
        entry = Signal(name=name, idwf=idwf, case_id=case_id, data_json=data or {})
        self.db.add(entry)
        await self.db.flush()

        logger.info(
            "SignalService: threw signal %s (idwf=%s case=%s)",
            name, idwf, case_id or "global",
        )
        return entry

    async def find_by_name(self, name: str) -> list[Signal]:
        """Fetch all signals matching a given name."""
        stmt = sa_select(Signal).where(Signal.name == name).order_by(Signal.created_at.asc())
        result = await self.db.execute(stmt)  # type: ignore[misc]
        return list(result.scalars().all())

    async def get_signals_by_case(self, case_id: str, idwf: str) -> list[Signal]:
        """Fetch all signals thrown by or associated with a specific case.

        Used for auditing and cleanup — returns all signal events linked to the
        given workflow/case pair regardless of status.

        Args:
            case_id: Case ID to query signals for.
            idwf: Workflow ID that threw the signals.

        Returns:
            List of ``Signal`` rows associated with the case/workflow, ordered by created_at ascending.
        """
        stmt = sa_select(Signal).where(
            Signal.case_id == case_id,
            Signal.idwf == idwf,
        ).order_by(Signal.created_at.asc())

        result = await self.db.execute(stmt)  # type: ignore[misc]
        return list(result.scalars().all())


def get_signal_service(db: AsyncSession):
    """FastAPI dependency that yields a bound ``SignalService``."""
    _cache: dict[int, SignalService] = {}

    def _get() -> SignalService:  # noqa: D401 — intentional factory closure
        key = id(db)
        if key not in _cache:
            _cache[key] = SignalService(db)
        return _cache[key]  # type: ignore[return-value]

    yield _get()


# Re-export for convenience.
__all__ = ["SignalService", "get_signal_service"]
