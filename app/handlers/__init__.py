"""Shape handler packages — each package auto-registers its handlers via ENGINE_HANDLER_REGISTRY at import time."""

from app.handlers.flow import SequenceFlowHandler, MessageFlowHandler  # noqa: F401
