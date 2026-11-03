from ascend_python_common.errors import INTERNAL, INTERNAL_FIXED_DETAIL, VALIDATION, resolve_detail

from src.api.exception_handlers import (
    FILE_TOO_LARGE,
    UPSTREAM_PROVIDER,
    FileSizeExceededError,
    UpstreamProviderError,
    error_registry,
)


def test_registry_maps_value_error_to_validation_400() -> None:
    # given
    exc = ValueError("oops")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == VALIDATION
    assert entry.code.status == 400
    assert entry.code.type_uri() == "https://ascend.ai/errors/validation"
    assert resolve_detail(entry, exc) == "oops"


def test_registry_maps_file_size_error_to_413_with_unchanged_type() -> None:
    # given
    exc = FileSizeExceededError("too big")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == FILE_TOO_LARGE
    assert entry.code.status == 413
    assert entry.code.type_uri() == "https://ascend.ai/errors/file-too-large"
    assert resolve_detail(entry, exc) == "too big"


def test_registry_maps_upstream_error_to_502_with_unchanged_type() -> None:
    # given
    exc = UpstreamProviderError("Hugging Face upstream call failed for model 'x'.")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == UPSTREAM_PROVIDER
    assert entry.code.status == 502
    assert entry.code.type_uri() == "https://ascend.ai/errors/upstream-provider"
    assert "Hugging Face upstream call failed" in resolve_detail(entry, exc)


def test_unregistered_error_falls_to_internal_with_fixed_detail() -> None:
    # given
    exc = RuntimeError("UPSTREAM_LEAK_MARKER")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is None
    assert INTERNAL.status == 500
    assert INTERNAL.type_uri() == "https://ascend.ai/errors/internal"
    assert INTERNAL_FIXED_DETAIL == "An unexpected error occurred. Check server logs for details."
