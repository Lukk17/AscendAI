import shlex
import tomllib
from pathlib import Path

REQUIRED_MYPY_FLAGS: dict[str, bool] = {
    "strict": True,
    "warn_unused_ignores": True,
    "warn_return_any": True,
    "warn_unreachable": True,
}

REQUIRED_PYTEST_ADDOPTS: tuple[str, ...] = (
    "--strict-markers",
    "--strict-config",
    "--cov-branch",
    "--cov-fail-under=100",
)

REQUIRED_PYTEST_FILTERWARNINGS_ENTRY = "error"

REQUIRED_PYTEST_XFAIL_STRICT = True

REQUIRED_PYTEST_ASYNCIO_MODE = "auto"

REQUIRED_RUFF_EXTEND_SUFFIX = "tooling/ruff.toml"

__all__ = [
    "REQUIRED_MYPY_FLAGS",
    "REQUIRED_PYTEST_ADDOPTS",
    "REQUIRED_PYTEST_ASYNCIO_MODE",
    "REQUIRED_PYTEST_FILTERWARNINGS_ENTRY",
    "REQUIRED_PYTEST_XFAIL_STRICT",
    "REQUIRED_RUFF_EXTEND_SUFFIX",
    "assert_pyproject_conforms",
]


def assert_pyproject_conforms(path: Path) -> None:
    data = _load_pyproject(path)
    _assert_mypy_conforms(data, path)
    _assert_pytest_conforms(data, path)
    _assert_ruff_conforms(data, path)


def _load_pyproject(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AssertionError(f"{path}: cannot read pyproject.toml: {exc}") from exc
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise AssertionError(f"{path}: invalid TOML: {exc}") from exc


def _tool_section(data: dict[str, object], *keys: str) -> dict[str, object] | None:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, dict) else None


def _assert_mypy_conforms(data: dict[str, object], path: Path) -> None:
    mypy = _tool_section(data, "tool", "mypy")
    if mypy is None:
        raise AssertionError(f"{path}: missing [tool.mypy] section")
    for flag, expected in REQUIRED_MYPY_FLAGS.items():
        if mypy.get(flag) is not expected:
            raise AssertionError(f"{path}: [tool.mypy] requires {flag} = true (strict mode)")
    if "disable_error_code" in mypy:
        raise AssertionError(f"{path}: [tool.mypy] must not set disable_error_code globally")


def _addopts_tokens(ini_options: dict[str, object]) -> list[str]:
    addopts = ini_options.get("addopts", [])
    if isinstance(addopts, str):
        return shlex.split(addopts)
    if isinstance(addopts, list):
        tokens: list[str] = []
        for item in addopts:
            tokens.extend(shlex.split(str(item)))
        return tokens
    return []


def _assert_pytest_conforms(data: dict[str, object], path: Path) -> None:
    ini_options = _tool_section(data, "tool", "pytest", "ini_options")
    if ini_options is None:
        raise AssertionError(f"{path}: missing [tool.pytest.ini_options] section")
    if ini_options.get("asyncio_mode") != REQUIRED_PYTEST_ASYNCIO_MODE:
        raise AssertionError(f'{path}: [tool.pytest.ini_options] requires asyncio_mode = "auto"')
    if ini_options.get("xfail_strict") is not REQUIRED_PYTEST_XFAIL_STRICT:
        raise AssertionError(f"{path}: [tool.pytest.ini_options] requires xfail_strict = true")
    warnings = ini_options.get("filterwarnings", [])
    entries = [str(item) for item in warnings] if isinstance(warnings, list) else [str(warnings)]
    if REQUIRED_PYTEST_FILTERWARNINGS_ENTRY not in entries:
        raise AssertionError(f'{path}: [tool.pytest.ini_options] requires filterwarnings with "error"')
    tokens = _addopts_tokens(ini_options)
    for required in REQUIRED_PYTEST_ADDOPTS:
        if required not in tokens:
            raise AssertionError(f"{path}: [tool.pytest.ini_options] addopts requires {required}")


def _assert_ruff_conforms(data: dict[str, object], path: Path) -> None:
    ruff = _tool_section(data, "tool", "ruff")
    if ruff is None:
        raise AssertionError(f"{path}: missing [tool.ruff] section with extend of the shared ruff file")
    extend = ruff.get("extend")
    values = [extend] if isinstance(extend, str) else list(extend) if isinstance(extend, list) else []
    if not any(REQUIRED_RUFF_EXTEND_SUFFIX in str(value) for value in values):
        raise AssertionError(
            f"{path}: [tool.ruff] must extend the shared ruff file ({REQUIRED_RUFF_EXTEND_SUFFIX})"
        )
