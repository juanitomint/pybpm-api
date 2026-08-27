"""Shape handler packages — each package auto-registers its handlers via ENGINE_HANDLER_REGISTRY at import time."""

from app.handlers.event import (
    IntermediateConditionalEventHandler,
    IntermediateErrorEventHandler,
    IntermediateLinkEventCatchingHandler,
    IntermediateMessageEventCatchingHandler,
    IntermediateSignalEventCatchingHandler,
    IntermediateTimerEventHandler,
)
from app.handlers.flow import MessageFlowHandler, SequenceFlowHandler
from app.handlers.gate import (
    ExclusiveDatabasedGatewayHandler,
    ParallelGatewayHandler,
)
from app.handlers.start_end import (
    EndCancelEventHandler,
    EndErrorEventHandler,
    EndMessageEventHandler,
    EndNoneEventHandler,
    EndTerminateEventHandler,
    GenericStartEventHandler,
    StartMessageEventHandler,
    StartNoneEventHandler,
    StartTimerEventHandler,
)
from app.handlers.subproc import CollapsedSubprocessHandler
from app.handlers.task import TaskHandler

__all__ = [
    "CollapsedSubprocessHandler",
    "EndCancelEventHandler",
    "EndErrorEventHandler",
    "EndMessageEventHandler",
    "EndNoneEventHandler",
    "EndTerminateEventHandler",
    "ExclusiveDatabasedGatewayHandler",
    "GenericStartEventHandler",
    "IntermediateConditionalEventHandler",
    "IntermediateErrorEventHandler",
    "IntermediateLinkEventCatchingHandler",
    "IntermediateMessageEventCatchingHandler",
    "IntermediateSignalEventCatchingHandler",
    "IntermediateTimerEventHandler",
    "MessageFlowHandler",
    "ParallelGatewayHandler",
    "SequenceFlowHandler",
    "StartMessageEventHandler",
    "StartNoneEventHandler",
    "StartTimerEventHandler",
    "TaskHandler",
]
