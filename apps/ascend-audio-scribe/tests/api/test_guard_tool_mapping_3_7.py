from pathlib import Path

import pytest

from src.api.mcp.mcp_server import (
    transcribe_audacity,
    transcribe_hf,
    transcribe_local,
    transcribe_openai,
)


@pytest.mark.asyncio
async def test_tool_refuses_unsupported_scheme_with_validation() -> None:
    # given
    uri = "ftp://example.com/audio.wav"
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        await transcribe_local(audio_uri=uri)
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_tool_refuses_private_address_with_validation() -> None:
    # given
    uri = "http://169.254.169.254/latest/meta-data"
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        await transcribe_openai(audio_uri=uri)
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_tool_refuses_user_info_uri_with_validation() -> None:
    # given
    uri = "https://user:secret@example.com/audio.mp3"
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        await transcribe_hf(audio_uri=uri)
    # then
    message = str(exc_info.value)
    assert message.startswith("validation: ")
    assert "secret" not in message


@pytest.mark.asyncio
async def test_tool_refuses_file_without_root_with_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
    uri = "file:///tmp/audio.wav"
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        await transcribe_audacity(audio_uri=uri)
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_tool_refuses_missing_file_inside_jail_with_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
    uri = (tmp_path / "missing.wav").as_uri()
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        await transcribe_local(audio_uri=uri)
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_tool_reraises_tool_error_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from fastmcp.exceptions import ToolError

    import src.api.mcp.mcp_server as mcp_module

    async def _boom(_uri: str) -> str:
        raise ToolError("boom")

    monkeypatch.setattr(mcp_module, "download_to_temp_async", _boom)
    # when
    with pytest.raises(ToolError, match="boom"):
        await transcribe_local(audio_uri="http://example.com/a.wav")
    # then
    assert True


@pytest.mark.asyncio
async def test_tool_openai_reraises_tool_error_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from fastmcp.exceptions import ToolError

    import src.api.mcp.mcp_server as mcp_module
    from src.config.config import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test")

    async def _boom(_uri: str) -> str:
        raise ToolError("boom-openai")

    monkeypatch.setattr(mcp_module, "download_to_temp_async", _boom)
    # when
    with pytest.raises(ToolError, match="boom-openai"):
        await transcribe_openai(audio_uri="http://example.com/a.wav")
    # then
    assert True


@pytest.mark.asyncio
async def test_tool_hf_reraises_tool_error_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from fastmcp.exceptions import ToolError

    import src.api.mcp.mcp_server as mcp_module
    from src.config.config import settings

    monkeypatch.setattr(settings, "HF_TOKEN", "test")

    async def _boom(_uri: str) -> str:
        raise ToolError("boom-hf")

    monkeypatch.setattr(mcp_module, "download_to_temp_async", _boom)
    # when
    with pytest.raises(ToolError, match="boom-hf"):
        await transcribe_hf(audio_uri="http://example.com/a.wav")
    # then
    assert True
