from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config.blocklist_loader import BlocklistLoader


def test_assets_dir_resolution():
    loader = BlocklistLoader()
    assert loader.assets_dir.name == "assets"
    assert loader.assets_dir.exists()


def test_assets_dir_explicit_path(tmp_path):
    loader = BlocklistLoader(assets_dir=str(tmp_path))
    assert loader.assets_dir == Path(tmp_path)
    assert loader.assets_dir.exists()


def test_ensure_assets_dir_creates_when_missing(tmp_path):
    target = tmp_path / "new-assets"
    BlocklistLoader(assets_dir=str(target))
    assert target.exists()


def test_load_rules_success():
    loader = BlocklistLoader()
    mock_content = b"||example.com^\n! Comment\n/ad_path"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = mock_content
    mock_response.raise_for_status = MagicMock()
    with patch("httpx.Client.get", return_value=mock_response) as mock_get:
        rules = loader.load_rules()
    mock_get.assert_called()
    assert rules.should_block("http://example.com")


def test_download_blocklist_raises_runtime_error_on_network_fail():
    loader = BlocklistLoader()
    with patch("httpx.Client.get", side_effect=Exception("network down")):
        with pytest.raises(RuntimeError):
            loader._download_blocklist()


def test_parse_rules_raises_file_not_found_when_path_missing(tmp_path):
    loader = BlocklistLoader(assets_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        loader._parse_rules()


def test_parse_rules_wraps_open_failure_in_runtime_error(tmp_path):
    loader = BlocklistLoader(assets_dir=str(tmp_path))
    loader.blocklist_path.write_text("||example.com^", encoding="utf-8")
    with patch("pathlib.Path.open", side_effect=PermissionError("read denied")):
        with pytest.raises(RuntimeError):
            loader._parse_rules()


def test_parse_rules_filters_comments_and_blank_lines(tmp_path):
    loader = BlocklistLoader(assets_dir=str(tmp_path))
    blob = "||example.com^\n! comment\n\n||other.com^\n"
    loader.blocklist_path.write_text(blob, encoding="utf-8")
    rules = loader._parse_rules()
    assert rules.should_block("http://example.com")
