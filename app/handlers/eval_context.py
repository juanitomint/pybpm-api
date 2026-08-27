"""Script task execution environment.

Provides the default objects available inside a Script task's script string,
mirroring legacy PHP ``run_Task()`` which injects ``$DS``, ``$idcase``,
``$idwf``, and transport ``$data`` into the eval scope.

Exported symbols:
    DataStorage   -- attribute/item-accessible view over case data (``ds.foo = 1``).
    build_script_namespace(token, case_data, transport_data) -- assembles the
        dict passed to Python's ``eval()`` as local namespace for scripts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class DataStorage:
    """Attribute/item-accessible view over case data, mirroring legacy PHP $DS.

    Uses ``defaultdict`` so reading an undefined attribute returns a nested
    empty ``DataStorage`` rather than raising ``AttributeError`` — mirrors the
    loose behavior of PHP's dynamic objects where ``$DS->undefined_var`` is
    harmless and evaluates as falsy.

    Scripts reference case variables by attribute (``ds.greeting = "hi"``) or
    item access (``ds["greeting"]``); both mutate the same underlying dict so
    changes survive across calls and are syncable back to BpmCase.data after
    eval finishes.
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any] | None = None):
        self._data: defaultdict[str, DataStorage] = defaultdict(lambda: DataStorage())
        if data:
            for k, v in data.items():
                self._data[k] = (
                    v
                    if isinstance(v, DataStorage)
                    else DataStorage(v)
                    if isinstance(v, dict)
                    else v
                )

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data[name]

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_data",):
            object.__setattr__(self, name, value)
        elif isinstance(value, dict) and not isinstance(value, DataStorage):
            self._data[name] = DataStorage(value)
        else:
            self._data[name] = value

    def __delattr__(self, name: str) -> None:
        if name.startswith("_"):
            raise AttributeError(name)
        # defaultdict silently swallows KeyError on missing keys — no-op.

    # -- Item access -------------------------------------------------------- #

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value if not isinstance(value, dict) else DataStorage(value)

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    # -- Mapping protocol --------------------------------------------------- #

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[type-arg]
        return self._data.get(key, default)

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __repr__(self) -> str:
        return f"DataStorage({dict(self._data)!r})"


# Reserved top-level keys injected by the namespace builder; transport data
# sharing a name with one of these is silently dropped to avoid shadowing
# identifiers that scripts rely on.
_RESERVED_KEYS = frozenset(("ds", "idwf", "idcase"))


def build_script_namespace(
    token: Any,
    case_data: dict[str, Any],
    transport_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the eval-local namespace for a Script task.

    Returns a plain dict suitable to pass as the ``local_ns`` argument of
    Python's ``eval()``. Shape:

        {
            "ds": DataStorage(case_data),   # mutable view; caller syncs back
            "idwf": <model id>,
            "idcase": <case id>,
            ...transport keys injected at top level (unless they collide with reserved)
        }

    Transport data is layered *after* the reserved identifiers so a transport
    key named ``ds`` / ``idwf`` / ``idcase`` cannot shadow them -- this matches
    legacy PHP's precedence where the engine-set variables always win.
    """
    ns: dict[str, Any] = {
        "ds": DataStorage(case_data),
        "idwf": token.idwf,
        "idcase": token.case_id,
    }

    if transport_data:
        for key, value in transport_data.items():
            if key not in _RESERVED_KEYS:
                ns[key] = value

    return ns
