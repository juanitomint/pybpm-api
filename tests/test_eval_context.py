"""Tests for the Script task execution environment (eval_context + _eval_script).

Covers:
- DataStorage attribute/item access with defaultdict safety.
- build_script_namespace key construction and transport-data precedence rules.
- _eval_script returns raw Python values (not coerced to bool) and None on error.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.handlers.eval_context import DataStorage, build_script_namespace
from app.handlers.flow import _eval_script

# --------------------------------------------------------------------------- #
# DataStorage
# --------------------------------------------------------------------------- #


class TestDataStorageBasicAccess:
    """Attribute and item access round-trip through the underlying dict."""

    def test_attribute_set_and_get(self):
        ds = DataStorage()
        ds.foo = 42
        assert ds.foo == 42

    def test_item_set_and_get(self):
        ds = DataStorage()
        ds["bar"] = "hello"
        assert ds["bar"] == "hello"

    def test_attribute_equals_item_access(self):
        ds = DataStorage()
        ds.baz = [1, 2]
        assert ds["baz"] == ds.baz == [1, 2]

    def test_missing_attribute_returns_nested_empty_ds(self):
        """Undefined variables on DS do NOT raise; they return a nested empty DS."""
        ds = DataStorage()
        result = ds.undefined_var
        assert isinstance(result, DataStorage)
        # Nested access keeps working without throwing.
        assert result.deep_key is not None  # defaultdict auto-creates

    def test_missing_item_returns_nested_empty_ds(self):
        """Same for __getitem__: undefined keys yield an empty nested DataStorage."""
        ds = DataStorage()
        result = ds["missing"]
        assert isinstance(result, DataStorage)


class TestDataStorageInitFromDict:
    """Construction from a pre-populated dict seeds the storage correctly."""

    def test_init_populates_keys(self):
        ds = DataStorage({"greeting": "hi", "count": 7})
        assert ds.greeting == "hi"
        assert ds.count == 7

    def test_nested_dict_wrapped_in_sub_ds(self):
        ds = DataStorage({"nested": {"inner": True}})
        assert isinstance(ds.nested, DataStorage)
        assert ds.nested.inner is True


class TestDataStorageMappingProtocol:
    """Standard mapping ops (len, iter, keys, get, contains) behave like a dict."""

    def test_len(self):
        ds = DataStorage({"a": 1, "b": 2})
        assert len(ds) == 2

    def test_contains(self):
        ds = DataStorage({"x": 10})
        assert "x" in ds
        assert "y" not in ds

    def test_get_with_default(self):
        ds = DataStorage()
        assert ds.get("missing", "fallback") == "fallback"


# --------------------------------------------------------------------------- #
# build_script_namespace
# --------------------------------------------------------------------------- #


def _make_token(idwf: str = "m1", case_id: str = "c1"):
    token = MagicMock()
    token.idwf = idwf
    token.case_id = case_id
    return token


class TestBuildScriptNamespace:
    """The namespace dict has ds/idwf/idcase plus any transport keys."""

    def test_reserved_keys_present(self):
        ns = build_script_namespace(_make_token(), {})
        assert isinstance(ns["ds"], DataStorage)
        assert ns["idwf"] == "m1"

        ns = build_script_namespace(_make_token(), {}, {"amount": 5, "source": "api"})
        assert ns["amount"] == 5
        assert ns["source"] == "api"

    def test_reserved_key_shadowing_drops_transport_value(self):
        """Transport data sharing a reserved name cannot override the identifier."""
        ns = build_script_namespace(
            _make_token(idwf="real-model", case_id="real-case"),
            {},
            {"idwf": "fake", "idcase": "fake"},
        )
        assert ns["idwf"] == "real-model"
        assert ns["idcase"] == "real-case"

    def test_none_transport_data_skipped(self):
        """Passing None as transport data skips the injection loop."""
        ns = build_script_namespace(_make_token(), {}, None)
        assert "amount" not in ns


# --------------------------------------------------------------------------- #
# _eval_script vs. _safe_eval
# --------------------------------------------------------------------------- #


class TestEvalScriptReturnsRawValue:
    """_eval_script returns the literal Python value, unlike _safe_eval's bool."""

    def test_int_returned(self):
        assert _eval_script("42") == 42

    def test_string_returned(self):
        assert _eval_script('"hello"') == "hello"

    def test_dict_returned(self):
        assert _eval_script('{"a": 1}') == {"a": 1}

    def test_none_on_syntax_error(self):
        # Malformed expression -> None (PHP's warning-and-continue semantics).
        assert _eval_script("42 +") is None

    def test_none_on_empty_expression(self):
        assert _eval_script("") is None
        assert _eval_script("   ") is None


class TestEvalScriptHasAccessToContext:
    """Names from the context dict are visible inside the expression."""

    def test_reads_transport_variable(self):
        ns = {"amount": 7}
        assert _eval_script("amount * 2", ns) == 14

    def test_reads_ds_attribute(self):
        ds = DataStorage({"greeting": "hi"})
        ns = {"ds": ds}
        # Attribute access resolves through __getattr__ -> _data lookup.
        result = _eval_script("ds.greeting + ' world'", ns)
        assert result == "hi world"


class TestEvalScriptIsSandboxed:
    """Builtins are stripped; scripts cannot reach Python internals."""

    def test_builtins_stripped(self):
        # __builtins__ is {} — any reference to a builtin name fails.
        assert _eval_script("len([1])") is None
        assert _eval_script("open('/etc/passwd')") is None
