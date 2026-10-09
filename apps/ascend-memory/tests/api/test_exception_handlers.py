from ascend_python_common.errors import INTERNAL, VALIDATION, resolve_detail

from src.api.exception_handlers import build_error_registry, error_registry


def test_registry_maps_value_error_to_validation_with_message() -> None:
    # given
    registry = build_error_registry()
    exc = ValueError("text must not be empty")
    # when
    entry = registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == VALIDATION
    assert resolve_detail(entry, exc) == "text must not be empty"


def test_registry_internal_code_is_internal() -> None:
    # given
    registry = build_error_registry()
    # when
    code = registry.internal_code
    # then
    assert code == INTERNAL


def test_registry_leaves_unexpected_exceptions_unmapped() -> None:
    # given
    exc = RuntimeError("upstream blew up")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is None
