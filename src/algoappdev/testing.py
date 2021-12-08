import os
from pathlib import Path

import algosdk as ag
import pytest
from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient

from algoappdev import clients, transactions
from algoappdev.utils import AccountMeta

NODE_DIR = Path(os.getenv("AAD_DATA", "/var/lib/algorand/nets/private_dev/Primary"))
WAIT_ROUNDS = int(os.getenv("ADD_WAIT_ROUNDS", 1))


@pytest.fixture(scope="module")
def algod_client() -> AlgodClient:
    return clients.build_algod_local_client(NODE_DIR)


@pytest.fixture(scope="module")
def kmd_client() -> AlgodClient:
    return clients.build_kmd_local_client(NODE_DIR)


def fund_account(
    algod_client: AlgodClient,
    kmd_client: KMDClient,
    microalgos: int,
) -> AccountMeta:
    account, txid = transactions.fund_from_genesis(algod_client, kmd_client, microalgos)
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)
    return account


@pytest.fixture
def funded_account(algod_client: AlgodClient, kmd_client: KMDClient) -> AccountMeta:
    return fund_account(algod_client, kmd_client, ag.util.algos_to_microalgos(1000))
