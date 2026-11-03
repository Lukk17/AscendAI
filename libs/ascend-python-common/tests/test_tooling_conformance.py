from pathlib import Path

import pytest

from ascend_python_common.tooling import assert_pyproject_conforms


def _write_conforming_pyproject(path: Path) -> None:
    # given
    content = """\
[tool.mypy]
python_version = "3.11"
strict = true
warn_unused_ignores = true
warn_return_any = true
warn_unreachable = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
xfail_strict = true
filterwarnings = ["error"]
addopts = [
    "--strict-markers",
    "--strict-config",
    "--cov-branch",
    "--cov-fail-under=100",
]

[tool.ruff]
extend = "tooling/ruff.toml"
"""
    # when
    path.write_text(content, encoding="utf-8")
    # then
    assert path.is_file()


def test_conforming_pyproject_passes(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    # when
    assert_pyproject_conforms(target)
    # then
    assert target.is_file()


def test_library_own_pyproject_passes() -> None:
    # given
    own = Path("pyproject.toml")
    # when
    assert_pyproject_conforms(own)
    # then
    assert own.is_file()


def test_check_fails_without_strict_true(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace("strict = true", "strict = false")
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="strict"):
        assert_pyproject_conforms(target)
    # then
    assert "strict = false" in target.read_text(encoding="utf-8")


def test_check_fails_with_global_disable_error_code(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace(
        "warn_unreachable = true",
        'warn_unreachable = true\ndisable_error_code = ["no-untyped-call"]',
    )
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="disable_error_code"):
        assert_pyproject_conforms(target)
    # then
    assert "disable_error_code" in target.read_text(encoding="utf-8")


def test_check_fails_without_strict_markers(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace('    "--strict-markers",\n', "")
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="strict-markers"):
        assert_pyproject_conforms(target)
    # then
    assert "--strict-markers" not in target.read_text(encoding="utf-8")


def test_check_fails_with_cov_fail_under_99(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace("--cov-fail-under=100", "--cov-fail-under=99")
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="cov-fail-under"):
        assert_pyproject_conforms(target)
    # then
    assert "--cov-fail-under=99" in target.read_text(encoding="utf-8")


def test_check_fails_without_filterwarnings_error(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace('filterwarnings = ["error"]', "filterwarnings = []")
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="filterwarnings"):
        assert_pyproject_conforms(target)
    # then
    assert "filterwarnings = []" in target.read_text(encoding="utf-8")


def test_check_fails_when_ruff_does_not_extend_shared_file(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace('extend = "tooling/ruff.toml"', "line-length = 110")
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="ruff"):
        assert_pyproject_conforms(target)
    # then
    assert "extend" not in target.read_text(encoding="utf-8")


def test_check_fails_for_missing_file(tmp_path: Path) -> None:
    # given
    target = tmp_path / "missing.toml"
    # when
    with pytest.raises(AssertionError, match="cannot read"):
        assert_pyproject_conforms(target)
    # then
    assert not target.exists()


def test_check_fails_for_invalid_toml(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    target.write_text("[[[not valid toml", encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="invalid TOML"):
        assert_pyproject_conforms(target)
    # then
    assert target.is_file()


def test_check_fails_when_tool_is_not_a_table(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    target.write_text('tool = "oops"\n', encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="mypy"):
        assert_pyproject_conforms(target)
    # then
    assert target.is_file()


def test_check_fails_when_mypy_section_is_missing(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace(
        '[tool.mypy]\npython_version = "3.11"\nstrict = true\n'
        "warn_unused_ignores = true\nwarn_return_any = true\nwarn_unreachable = true\n\n",
        "",
    )
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="mypy"):
        assert_pyproject_conforms(target)
    # then
    assert "[tool.mypy]" not in target.read_text(encoding="utf-8")


def test_check_fails_when_mypy_warn_flag_is_missing(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace("warn_return_any = true\n", "")
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="warn_return_any"):
        assert_pyproject_conforms(target)
    # then
    assert "warn_return_any" not in target.read_text(encoding="utf-8")


def test_check_fails_when_pytest_section_is_missing(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8")
    text = text.split("[tool.pytest.ini_options]", 1)[0]
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="pytest"):
        assert_pyproject_conforms(target)
    # then
    assert "ini_options" not in target.read_text(encoding="utf-8")


def test_check_fails_when_asyncio_mode_is_not_auto(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace('asyncio_mode = "auto"', 'asyncio_mode = "strict"')
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="asyncio_mode"):
        assert_pyproject_conforms(target)
    # then
    assert 'asyncio_mode = "strict"' in target.read_text(encoding="utf-8")


def test_check_fails_when_xfail_strict_is_not_true(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace("xfail_strict = true", "xfail_strict = false")
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="xfail_strict"):
        assert_pyproject_conforms(target)
    # then
    assert "xfail_strict = false" in target.read_text(encoding="utf-8")


def test_check_fails_when_addopts_is_not_a_list_or_string(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8")
    start = text.index("addopts = [")
    end = text.index("]", start) + 1
    text = text[:start] + "addopts = 5" + text[end:]
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="strict-markers"):
        assert_pyproject_conforms(target)
    # then
    assert "addopts = 5" in target.read_text(encoding="utf-8")


def test_check_passes_with_string_addopts(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8")
    start = text.index("addopts = [")
    end = text.index("]", start) + 1
    text = (
        text[:start]
        + 'addopts = "--strict-markers --strict-config --cov-branch --cov-fail-under=100"'
        + text[end:]
    )
    target.write_text(text, encoding="utf-8")
    # when
    assert_pyproject_conforms(target)
    # then
    assert "--strict-markers" in target.read_text(encoding="utf-8")


def test_check_passes_with_string_filterwarnings(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace(
        'filterwarnings = ["error"]', 'filterwarnings = "error"'
    )
    target.write_text(text, encoding="utf-8")
    # when
    assert_pyproject_conforms(target)
    # then
    assert 'filterwarnings = "error"' in target.read_text(encoding="utf-8")


def test_check_passes_with_ruff_extend_list(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").replace(
        'extend = "tooling/ruff.toml"', 'extend = ["tooling/ruff.toml"]'
    )
    target.write_text(text, encoding="utf-8")
    # when
    assert_pyproject_conforms(target)
    # then
    assert 'extend = ["tooling/ruff.toml"]' in target.read_text(encoding="utf-8")


def test_check_fails_when_ruff_section_is_missing(tmp_path: Path) -> None:
    # given
    target = tmp_path / "pyproject.toml"
    _write_conforming_pyproject(target)
    text = target.read_text(encoding="utf-8").split("[tool.ruff]", 1)[0]
    target.write_text(text, encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="ruff"):
        assert_pyproject_conforms(target)
    # then
    assert "[tool.ruff]" not in target.read_text(encoding="utf-8")
