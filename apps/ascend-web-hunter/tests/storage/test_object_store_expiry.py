import secrets
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from src.storage.object_store import EXPIRY_RULE_ID, ObjectStore


def _store() -> tuple[ObjectStore, Stubber]:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key=secrets.token_hex(8),
    )
    stubber = Stubber(client)
    stubber.activate()
    return ObjectStore(client), stubber


def _own_rule(days: int) -> dict[str, Any]:
    return {
        "ID": EXPIRY_RULE_ID,
        "Status": "Enabled",
        "Filter": {"Prefix": "tenant/"},
        "Expiration": {"Days": days},
    }


_OTHER_RULE: dict[str, Any] = {
    "ID": "operator-archive",
    "Status": "Enabled",
    "Filter": {"Prefix": "archive/"},
    "Expiration": {"Days": 30},
}


async def test_set_expiry_on_a_bucket_without_lifecycle_puts_one_prefix_rule_in_days() -> None:
    # given a bucket with no lifecycle configuration
    store, stubber = _store()
    stubber.add_client_error(
        "get_bucket_lifecycle_configuration",
        service_error_code="NoSuchLifecycleConfiguration",
        http_status_code=404,
        expected_params={"Bucket": "crawls"},
    )
    stubber.add_response(
        "put_bucket_lifecycle_configuration",
        {},
        {"Bucket": "crawls", "LifecycleConfiguration": {"Rules": [_own_rule(7)]}},
    )

    # when
    await store.set_expiry("crawls", "tenant/", 7)

    # then the store received exactly that rule
    stubber.assert_no_pending_responses()


async def test_set_expiry_keeps_other_rules_and_replaces_its_own_by_id() -> None:
    # given a bucket holding an operator rule and an older copy of the service rule
    store, stubber = _store()
    stubber.add_response(
        "get_bucket_lifecycle_configuration",
        {
            "Rules": [_OTHER_RULE, _own_rule(3)],
            "TransitionDefaultMinimumObjectSize": "varies_by_storage_class",
        },
        {"Bucket": "crawls"},
    )
    stubber.add_response(
        "put_bucket_lifecycle_configuration",
        {},
        {
            "Bucket": "crawls",
            "LifecycleConfiguration": {"Rules": [_OTHER_RULE, _own_rule(7)]},
            "TransitionDefaultMinimumObjectSize": "varies_by_storage_class",
        },
    )

    # when
    await store.set_expiry("crawls", "tenant/", 7)

    # then the operator rule and the bucket setting survive and the service rule carries the new days
    stubber.assert_no_pending_responses()


async def test_set_expiry_raises_a_refused_read() -> None:
    # given a store that refuses to read the lifecycle configuration
    store, stubber = _store()
    stubber.add_client_error("get_bucket_lifecycle_configuration", service_error_code="AccessDenied")

    # when / then the refusal reaches the caller and nothing is written
    with pytest.raises(ClientError, match="AccessDenied"):
        await store.set_expiry("crawls", "tenant/", 7)
    stubber.assert_no_pending_responses()


async def test_set_expiry_raises_a_refused_write() -> None:
    # given a store that refuses the rule
    store, stubber = _store()
    stubber.add_response("get_bucket_lifecycle_configuration", {"Rules": []}, {"Bucket": "crawls"})
    stubber.add_client_error("put_bucket_lifecycle_configuration", service_error_code="AccessDenied")

    # when / then the refusal reaches the caller
    with pytest.raises(ClientError, match="AccessDenied"):
        await store.set_expiry("crawls", "tenant/", 7)
