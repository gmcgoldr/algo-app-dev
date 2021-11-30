import os
from pathlib import Path

import pytest
from algosdk.v2client.algod import AlgodClient

from pyteal_utils import clients


@pytest.fixture(scope="module")
def node_dir() -> Path:
    return Path(os.getenv("ALGORAND_DATA"))


@pytest.fixture(scope="module")
def algod_client(node_dir: Path) -> AlgodClient:
    return clients.build_algod_local_client(node_dir)


@pytest.fixture(scope="module")
def kmd_client(node_dir: Path) -> AlgodClient:
    return clients.build_kmd_local_client(node_dir)
