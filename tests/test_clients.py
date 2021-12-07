import base64
from unittest import mock

from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient

from pyteal_utils import clients


def test_builds_local_algod_client(algod_client: AlgodClient):
    assert algod_client


def test_builds_local_kmd_client(kmd_client: KMDClient):
    assert kmd_client


def test_get_app_global_key_returns_value():
    key = base64.b64encode("a".encode("utf8")).decode("ascii")
    value = base64.b64encode("b".encode("utf8")).decode("ascii")
    info = {
        "params": {
            "global-state": [
                {"key": ""},
                {},
                {"key": key, "value": {"type": 1, "bytes": value}},
            ]
        }
    }
    assert clients.get_app_global_key(info, key="a") == b"b"
    assert clients.get_app_global_key(info, key="") is None
    assert clients.get_app_global_key(info, key="b") is None


def test_get_app_local_key_returns_value():
    key = base64.b64encode("a".encode("utf8")).decode("ascii")
    value = base64.b64encode("c".encode("utf8")).decode("ascii")
    info = {
        "apps-local-state": [
            {
                "id": 1,
                "key-value": [
                    {"key": ""},
                    {},
                    {"key": key, "value": {"type": 1, "bytes": value}},
                ],
            }
        ]
    }
    assert clients.get_app_local_key(info, 1, key="a") == b"c"
    assert clients.get_app_local_key(info, 2, key="a") is None
    assert clients.get_app_local_key(info, 1, key="") is None
    assert clients.get_app_local_key(info, 1, key="b") is None
