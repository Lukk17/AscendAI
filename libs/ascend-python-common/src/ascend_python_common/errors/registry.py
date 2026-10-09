from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ascend_python_common.errors.codes import INTERNAL, INTERNAL_FIXED_DETAIL, ProblemCode

DetailRule = str | Callable[[BaseException], str]
HeadersRule = dict[str, str] | Callable[[BaseException], dict[str, str] | None] | None
ExtensionsRule = dict[str, Any] | Callable[[BaseException], dict[str, Any] | None] | None


@dataclass(frozen=True, slots=True)
class ErrorEntry:
    code: ProblemCode
    detail: DetailRule
    headers: HeadersRule = None
    extensions: ExtensionsRule = None
    expected: bool = False


@dataclass
class ErrorRegistry:
    internal_code: ProblemCode = INTERNAL
    _entries: dict[type[Exception], ErrorEntry] = field(default_factory=dict)

    def register(
        self,
        exc_type: type[Exception],
        code: ProblemCode,
        detail: DetailRule,
        headers: HeadersRule = None,
        extensions: ExtensionsRule = None,
        expected: bool = False,
    ) -> None:
        if code == self.internal_code and (not isinstance(detail, str) or detail != INTERNAL_FIXED_DETAIL):
            raise ValueError("internal code entry must use the fixed detail")
        self._entries[exc_type] = ErrorEntry(
            code=code, detail=detail, headers=headers, extensions=extensions, expected=expected
        )

    def lookup(self, exc: BaseException) -> ErrorEntry | None:
        for exc_type, entry in self._entries.items():
            if isinstance(exc, exc_type):
                return entry
        return None

    @property
    def entries(self) -> dict[type[Exception], ErrorEntry]:
        return dict(self._entries)


def resolve_detail(entry: ErrorEntry, exc: BaseException) -> str:
    if isinstance(entry.detail, str):
        return entry.detail
    return entry.detail(exc)


def resolve_headers(entry: ErrorEntry, exc: BaseException) -> dict[str, str] | None:
    headers = entry.headers
    if headers is None:
        return None
    if callable(headers):
        return headers(exc)
    return headers


def resolve_extensions(entry: ErrorEntry, exc: BaseException) -> dict[str, Any] | None:
    extensions = entry.extensions
    if extensions is None:
        return None
    if callable(extensions):
        return extensions(exc)
    return extensions


__all__ = [
    "DetailRule",
    "ErrorEntry",
    "ErrorRegistry",
    "ExtensionsRule",
    "HeadersRule",
    "resolve_detail",
    "resolve_extensions",
    "resolve_headers",
]
