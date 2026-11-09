import configparser
from pathlib import Path

_SUPERVISORD_CONF = Path(__file__).resolve().parents[2] / "supervisord.conf"


def _program_command(program: str) -> list[str]:
    parser = configparser.RawConfigParser()
    parser.read(_SUPERVISORD_CONF, encoding="utf-8")
    return parser.get(f"program:{program}", "command").split()


def test_x11vnc_listens_on_the_loopback_address_only() -> None:
    # when
    command = _program_command("x11vnc")

    # then
    assert "-localhost" in command
    assert "-listen" not in command


def test_websockify_reaches_x11vnc_over_the_loopback_address() -> None:
    # when
    command = _program_command("novnc")

    # then
    assert command[0] == "websockify"
    assert command[-1] == "localhost:5900"
