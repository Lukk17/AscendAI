from unittest.mock import MagicMock, patch

import pytest

from src.config.blocklist_loader import BlocklistLoader


@pytest.fixture
def mock_loader():
    return BlocklistLoader()


def test_load_rules_success(mock_loader):
    # given
    mock_content = b"||example.com^\n! Comment\n/ad_path"  # Must be bytes
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = mock_content
    mock_response.text = mock_content.decode()

    # when
    with patch("httpx.Client.get", return_value=mock_response) as mock_get:
        rules = mock_loader.load_rules()

        # then
        mock_get.assert_called()
        # Verify that rules are loaded (implementation specific check)
        # Assuming adblockparser is used internally, we can check if a rule matches
        assert rules.should_block("http://example.com")
        assert not rules.should_block("http://good-site.com")


def test_load_rules_network_error(mock_loader):
    # when
    with patch("httpx.Client.get", side_effect=Exception("Network fail")):
        # then

        with pytest.raises(Exception):
            mock_loader.load_rules()


def test_assets_dir_resolution(mock_loader):
    # then
    assert mock_loader.assets_dir.name == "assets"
    assert mock_loader.assets_dir.exists()
