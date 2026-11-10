from pathlib import Path

from ascend_python_common.tooling import assert_pyproject_conforms


def test_pyproject_conforms_to_shared_tooling() -> None:
    # given
    own = Path("pyproject.toml")
    # when
    assert_pyproject_conforms(own)
    # then
    assert own.is_file()
