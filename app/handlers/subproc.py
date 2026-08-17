"""CollapsedSubprocess shape handler (v1 stub).

Mirrors legacy ``run_CollapsedSubprocess()`` from
``dna2bpm/application/modules/bpm/helpers/bpmn2.0/subproc_helper.php:1-236``.

Full subprocess orchestration — child case creation per subprocesstype/looptype
combination, sequential/parallel iteration, completion-condition evaluation — is
~240 lines of PHP and depends on services (`Bpm::gen_case()`, `Bpm::Startcase()`)
that do not yet exist in pybpm-api. For v1 compatibility this handler just calls
``movenext`` so non-looping subprocesses advance through the diagram correctly;
looping/collapsible subprocesses will silently skip their child-case logic until a
follow-up PR wires it up.

A class-level ``_TODO_FULL_SUBPROC`` marker documents the deferred work so the
next implementer sees exactly what is missing without re-reading the PHP source.
"""

from __future__ import annotations

from typing import Any


class CollapsedSubprocessHandler:
    """Handle a token arriving on a CollapsedSubprocess shape.

    v1 stub — advances via movenext, defers full subprocess orchestration.

    Mirrors legacy ``run_CollapsedSubprocess()`` (subproc_helper.php:1-236).
    """

    _STENCIL_ID = "CollapsedSubprocess"

    # TODO (Phase 3b): implement full subprocess orchestration:
    #   - Evaluate looptype (Sequential / Parallel / Standard) to decide whether
    #     to create child cases or skip.
    #   - For subprocesstype in ("Independent", "Reference"), call
    #     Bpm::gen_case() with the shape's ``entry`` property as the child idwf,
    #     pass parent case context via data['parent'], then invoke engine.run on
    #     each child.
    #   - Evaluate completioncondition expression; if all children satisfy it,
    #     move next on this subprocess container.
    _TODO_FULL_SUBPROC = True

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:  # noqa: ANN001, D401
        """v1 stub — call movenext and advance."""
        await service.movenext(token.resource_id, token.idwf, token.case_id)
        return False


# Auto-register at import time via the registry pattern.
from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY  # noqa: E402

ENGINE_HANDLER_REGISTRY.register(CollapsedSubprocessHandler._STENCIL_ID, CollapsedSubprocessHandler)
