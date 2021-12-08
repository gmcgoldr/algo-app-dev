"""
Utilities to connect to and interact with `algod` and `kmd` clients.
"""

import base64
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Union

from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient

from . import utils


def build_algod_local_client(data_dir: Path) -> AlgodClient:
    """
    Build the `algod` client to interface with the local daemon whose
    congifugartion network configruation is at `data_dir`.

    Args:
        data_dir: the path with the network data

    Returns:
        the client connected to the local algod daemon
    """
    algod_address = (data_dir / "algod.net").read_text().strip()
    algod_token = (data_dir / "algod.token").read_text().strip()
    algod_client = AlgodClient(
        algod_address=f"http://{algod_address}", algod_token=algod_token
    )
    return algod_client


def build_kmd_local_client(data_dir: Path, version: str = "0.5") -> KMDClient:
    """
    Build the `kmd` client to interface with the local daemon whose
    congifugartion network configruation is at `data_dir`.

    Args:
        data_dir: the path with the network data

    Returns:
        the client connected to the local kmd daemon
    """
    kmd_address = (data_dir / f"kmd-v{version}" / "kmd.net").read_text().strip()
    kmd_token = (data_dir / f"kmd-v{version}" / "kmd.token").read_text().strip()
    kmd_client = KMDClient(kmd_address=f"http://{kmd_address}", kmd_token=kmd_token)
    return kmd_client


def get_app_global_key(app_state: Dict, key: str) -> Union[int, bytes]:
    """
    Return the value for the given `key` in `app_id`'s global data.
    """
    key = base64.b64encode(key.encode("utf8")).decode("ascii")
    for key_state in app_state.get("params", {}).get("global-state", []):
        if key_state.get("key", None) != key:
            continue
        return utils.from_value(key_state.get("value", None))
    return None


def get_app_local_key(account_state: Dict, app_id: int, key: str) -> Union[int, bytes]:
    """
    Return the value for the given `key` in `app_id`'s local data for account
    `address`.
    """
    key = base64.b64encode(key.encode("utf8")).decode("ascii")
    for app_state in account_state.get("apps-local-state", []):
        if app_state.get("id", None) != app_id:
            continue
        for key_state in app_state.get("key-value", []):
            if key_state.get("key", None) != key:
                continue
            return utils.from_value(key_state.get("value", None))
    return None
