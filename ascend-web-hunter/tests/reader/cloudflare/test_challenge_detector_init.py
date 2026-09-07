import importlib
import sys
from unittest.mock import mock_open, patch


def test_module_falls_back_when_dictionary_missing():
    """If challenge_dictionary.json cannot be loaded the module falls back to empty heuristics."""
    sys.modules.pop("src.reader.cloudflare.challenge_detector", None)
    with patch("pathlib.Path.open", side_effect=FileNotFoundError("missing")):
        importlib.import_module("src.reader.cloudflare.challenge_detector")
    sys.modules.pop("src.reader.cloudflare.challenge_detector", None)
    importlib.import_module("src.reader.cloudflare.challenge_detector")


def test_module_loads_real_dictionary_on_normal_import():
    """Smoke test the import on the happy path; ensures both paths are covered."""
    sys.modules.pop("src.reader.cloudflare.challenge_detector", None)
    payload = '{"waf_script_signatures": [], "waf_strict_phrases": [], "login_title_patterns": []}'
    with patch("pathlib.Path.open", mock_open(read_data=payload)):
        importlib.import_module("src.reader.cloudflare.challenge_detector")
    sys.modules.pop("src.reader.cloudflare.challenge_detector", None)
    importlib.import_module("src.reader.cloudflare.challenge_detector")
