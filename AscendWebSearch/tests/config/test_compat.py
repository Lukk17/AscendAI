import sys
from types import SimpleNamespace
from unittest.mock import patch

from src.config.compat import Compat, apply_compatibility_patches


def test_compat_headers_contains_header_key():
    container = Compat("headers")
    assert "headers_input.json" in container


def test_compat_headers_does_not_contain_unrelated_key():
    container = Compat("headers")
    assert "fingerprints_data.json" not in container


def test_compat_fingerprints_always_returns_false_for_contains():
    container = Compat("fingerprints")
    assert "anything.json" not in container


def test_compat_getitem_returns_key_unchanged():
    container = Compat("headers")
    assert container["foo.json"] == "foo.json"


def test_apply_patches_injects_when_attribute_missing(monkeypatch):
    fake_module = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "browserforge", SimpleNamespace(download=fake_module))
    monkeypatch.setitem(sys.modules, "browserforge.download", fake_module)
    apply_compatibility_patches()
    assert hasattr(fake_module, "DATA_FILES")
    assert "headers" in fake_module.DATA_FILES
    assert "fingerprints" in fake_module.DATA_FILES


def test_apply_patches_skips_when_attribute_present(monkeypatch):
    sentinel = {"headers": "sentinel"}
    fake_module = SimpleNamespace(DATA_FILES=sentinel)
    monkeypatch.setitem(sys.modules, "browserforge", SimpleNamespace(download=fake_module))
    monkeypatch.setitem(sys.modules, "browserforge.download", fake_module)
    apply_compatibility_patches()
    assert fake_module.DATA_FILES is sentinel


def test_apply_patches_swallows_import_error():
    with patch.dict(sys.modules, {"browserforge.download": None}):
        apply_compatibility_patches()


def test_apply_patches_swallows_generic_exception(monkeypatch):
    fake_module = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "browserforge", SimpleNamespace(download=fake_module))
    monkeypatch.setitem(sys.modules, "browserforge.download", fake_module)
    with patch("src.config.compat.hasattr", side_effect=RuntimeError("boom")):
        apply_compatibility_patches()
