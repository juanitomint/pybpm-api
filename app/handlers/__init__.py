"""Shape handler packages — each package auto-registers its handlers via ENGINE_HANDLER_REGISTRY at import time."""

from app.handlers.flow import SequenceFlowHandler, MessageFlowHandler  # noqa: F401
from app.handlers.start_end import (  # noqa: F401
    StartNoneEventHandler,
    StartMessageEventHandler,
    StartTimerEventHandler,
    GenericStartEventHandler,
    EndNoneEventHandler,
    EndMessageEventHandler,
    _SignalThrowingEndHandler,
    EndErrorEventHandler,
    EndCancelEventHandler,
    EndTerminateEventHandler,
)
from app.handlers.task import TaskHandler  # noqa: F401
from app.handlers.gate import (  # noqa: F401
    ParallelGatewayHandler,
    ExclusiveDatabasedGatewayHandler,
)
from app.handlers.subproc import CollapsedSubprocessHandler  # noqa: F401
from app.handlers.event import (  # noqa: F401
    IntermediateTimerEventHandler,
    IntermediateMessageEventCatchingHandler,
    IntermediateSignalEventCatchingHandler,
    IntermediateErrorEventHandler,
    IntermediateConditionalEventHandler,
    IntermediateLinkEventCatchingHandler,
)
