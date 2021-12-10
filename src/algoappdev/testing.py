"""Utilities for testing apps."""

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
    """
    Build the client connected to the local `algod` daemon.

    Finds the daemon operating on the data at the directory stored in the
    environment variable `ADD_DATA`.
    """
    return clients.build_algod_local_client(NODE_DIR)


@pytest.fixture(scope="module")
def kmd_client() -> AlgodClient:
    """
    Build the client connected to the local `kmd` daemon.

    Finds the daemon operating on the data at the directory stored in the
    environment variable `ADD_DATA`.
    """
    return clients.build_kmd_local_client(NODE_DIR)


def fund_account(
    algod_client: AlgodClient,
    kmd_client: KMDClient,
    microalgos: int,
) -> AccountMeta:
    """
    Use funds from the genesis account to fund a new account.

    Args:
        algod_client: the client to which the transaction is submitted
        kmd_client: the client which signs the transaction for the genesis
            account
        microalgos: the quantity of microAlgos to add to the new account

    Returns:
        the meta data of the newly funded account
    """
    account, txid = transactions.fund_from_genesis(algod_client, kmd_client, microalgos)
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)
    return account


@pytest.fixture
def funded_account(algod_client: AlgodClient, kmd_client: KMDClient) -> AccountMeta:
    """
    Create a new account and add 1 Algo of funds to it. See `fund_account`.
    """
    return fund_account(algod_client, kmd_client, ag.util.algos_to_microalgos(1000))
