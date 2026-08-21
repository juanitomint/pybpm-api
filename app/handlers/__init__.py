"""Shape handler packages — each package auto-registers its handlers via ENGINE_HANDLER_REGISTRY at import time."""

from app.handlers.event import (  # noqa: F401
    IntermediateConditionalEventHandler,
    IntermediateErrorEventHandler,
    IntermediateLinkEventCatchingHandler,
    IntermediateMessageEventCatchingHandler,
    IntermediateSignalEventCatchingHandler,
    IntermediateTimerEventHandler,
)
from app.handlers.flow import MessageFlowHandler, SequenceFlowHandler  # noqa: F401
from app.handlers.gate import (  # noqa: F401
    ExclusiveDatabasedGatewayHandler,
    ParallelGatewayHandler,
)
from app.handlers.start_end import (  # noqa: F401
    EndCancelEventHandler,
    EndErrorEventHandler,
    EndMessageEventHandler,
    EndNoneEventHandler,
    EndTerminateEventHandler,
    GenericStartEventHandler,
    StartMessageEventHandler,
    StartNoneEventHandler,
    StartTimerEventHandler,
    _SignalThrowingEndHandler,
)
from app.handlers.subproc import CollapsedSubprocessHandler  # noqa: F401
from app.handlers.task import TaskHandler  # noqa: F401
