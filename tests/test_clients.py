import os
from pathlib import Path
from unittest import mock

from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient

from pyteal_utils import clients


def test_builds_local_algod_client(algod_client: AlgodClient):
    assert algod_client


def test_builds_local_kmd_client(kmd_client: KMDClient):
    assert kmd_client


def test_gets_wallet_id(kmd_client: KMDClient):
    assert clients.get_wallet_id(kmd_client, "unencrypted-default-wallet")


def test_gets_wallet_id_none_if_missing(kmd_client: KMDClient):
    assert clients.get_wallet_id(kmd_client, "does-not-exist") is None


def test_gets_wallet_handle(kmd_client: KMDClient):
    wallet_id = clients.get_wallet_id(kmd_client, "unencrypted-default-wallet")
    with clients.get_wallet_handle(kmd_client, wallet_id, "") as handle:
        assert handle


def test_gets_wallet_handle_release():
    client = mock.Mock()
    client.init_wallet_handle.return_value = "handle"
    with clients.get_wallet_handle(client, "wallet_id", "wallet_password") as handle:
        assert handle == "handle"
    client.assert_has_calls(
        [
            mock.call.init_wallet_handle("wallet_id", "wallet_password"),
            mock.call.release_wallet_handle("handle"),
        ]
    )
