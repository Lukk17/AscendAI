import secrets
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from src.storage.object_store import ObjectStore, build_client

_ACCESS_KEY = "test"
_SECRET_KEY = secrets.token_hex(8)


def _store() -> tuple[ObjectStore, Stubber]:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
    )
    stubber = Stubber(client)
    stubber.activate()
    return ObjectStore(client), stubber


def test_build_client_uses_configured_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "OBJECT_STORE_S3_ENDPOINT", "http://localhost:9070")

    # when
    client = build_client()

    # then
    assert client.meta.endpoint_url == "http://localhost:9070"


@pytest.fixture
def page_file(tmp_path: Path) -> Path:
    path = tmp_path / "page.md"
    path.write_text("hello", encoding="utf-8")
    return path


async def test_upload_file_puts_small_file(page_file: Path) -> None:
    # given
    store, stubber = _store()
    stubber.add_response("put_object", {})

    # when
    await store.upload_file(str(page_file), "b", "k")

    # then
    stubber.assert_no_pending_responses()


async def test_put_and_get_json_round_trip() -> None:
    # given
    store, stubber = _store()
    stubber.add_response("put_object", {}, {"Bucket": "b", "Key": "k", "Body": b'{"a": 1}'})
    stubber.add_response("get_object", {"Body": _AsyncBody(b'{"a": 1}')}, {"Bucket": "b", "Key": "k"})

    # when / then
    await store.put_json("b", "k", {"a": 1})
    assert await store.get_json("b", "k") == {"a": 1}
    stubber.assert_no_pending_responses()


async def test_put_and_get_text_round_trip() -> None:
    # given
    store, stubber = _store()
    stubber.add_response("put_object", {}, {"Bucket": "b", "Key": "k", "Body": b"hello"})
    stubber.add_response("get_object", {"Body": _AsyncBody(b"hello")}, {"Bucket": "b", "Key": "k"})

    # when / then
    await store.put_text("b", "k", "hello")
    assert await store.get_text("b", "k") == "hello"
    stubber.assert_no_pending_responses()


async def test_put_bytes() -> None:
    # given
    store, stubber = _store()
    stubber.add_response("put_object", {})

    # when / then
    await store.put_bytes("b", "k", b"a\nb\n")
    stubber.assert_no_pending_responses()


async def test_get_text_missing_answers_none() -> None:
    # given
    store, stubber = _store()
    stubber.add_client_error("get_object", "NoSuchKey", "missing", 404)

    # when / then
    assert await store.get_text("b", "k") is None


async def test_get_text_other_error_raises() -> None:
    # given
    store, stubber = _store()
    stubber.add_client_error("get_object", "InternalError", "boom", 500)

    # when / then
    with pytest.raises(ClientError):
        await store.get_text("b", "k")


async def test_head_true_false_and_error() -> None:
    # given
    store, stubber = _store()
    stubber.add_response("head_object", {}, {"Bucket": "b", "Key": "k"})
    stubber.add_client_error("head_object", "NotFound", "gone", 404)
    stubber.add_client_error("head_object", "InternalError", "boom", 500)

    # when / then
    assert await store.head("b", "k") is True
    assert await store.head("b", "k") is False
    with pytest.raises(ClientError):
        await store.head("b", "k")


async def test_delete_and_copy() -> None:
    # given
    store, stubber = _store()
    stubber.add_response("delete_object", {}, {"Bucket": "b", "Key": "k"})
    stubber.add_response(
        "copy_object", {}, {"Bucket": "b", "Key": "d", "CopySource": {"Bucket": "b", "Key": "s"}}
    )

    # when / then
    await store.delete("b", "k")
    await store.copy_inside_bucket("b", "s", "d")
    stubber.assert_no_pending_responses()


async def test_list_prefix_with_and_without_continuation() -> None:
    # given
    store, stubber = _store()
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "a"}], "NextContinuationToken": "tok"},
        {"Bucket": "b", "Prefix": "p"},
    )
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "b"}]},
        {"Bucket": "b", "Prefix": "p", "ContinuationToken": "tok"},
    )

    # when / then
    keys, token = await store.list_prefix("b", "p")
    assert (keys, token) == (["a"], "tok")
    keys, token = await store.list_prefix("b", "p", token)
    assert (keys, token) == (["b"], None)


async def test_list_prefix_empty_answers_no_keys() -> None:
    # given
    store, stubber = _store()
    stubber.add_response("list_objects_v2", {}, {"Bucket": "b", "Prefix": "p"})

    # when / then
    assert await store.list_prefix("b", "p") == ([], None)


async def test_ensure_bucket_existing_and_created() -> None:
    # given
    store, stubber = _store()
    stubber.add_response("head_bucket", {}, {"Bucket": "b"})
    stubber.add_client_error("head_bucket", "NotFound", "gone", 404)
    stubber.add_response("create_bucket", {})
    stubber.add_client_error("head_bucket", "404", "gone", 404)
    stubber.add_response("create_bucket", {})

    # when / then
    await store.ensure_bucket("b")
    await store.ensure_bucket("b2")
    await store.ensure_bucket("b3")
    stubber.assert_no_pending_responses()


async def test_ensure_bucket_other_error_raises() -> None:
    # given
    store, stubber = _store()
    stubber.add_client_error("head_bucket", "InternalError", "boom", 500)

    # when / then
    with pytest.raises(ClientError):
        await store.ensure_bucket("b")


async def test_presign_get() -> None:
    # given
    store, stubber = _store()

    # when
    url = await store.presign_get("b", "k")

    # then a URL for the key is returned
    assert url.startswith("https://")
    assert "k" in url


class _AsyncBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


def test_no_other_module_creates_s3_client() -> None:
    # given the service sources
    import pathlib

    roots = [pathlib.Path("src/storage/object_store.py")]

    # when every source file is searched for a client construction
    offenders = []
    for path in pathlib.Path("src").rglob("*.py"):
        if path in roots or "__pycache__" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        if "boto3.client" in text or "boto3.resource" in text:
            offenders.append(str(path))

    # then only the shared client module creates one
    assert offenders == []
