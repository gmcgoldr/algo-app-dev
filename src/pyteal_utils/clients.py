"""
Utilities to connect to and interact with `algod` and `kmd` clients.
"""

from contextlib import contextmanager
from pathlib import Path

from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient


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


def get_wallet_id(kmd_client: KMDClient, name: str) -> str:
    """
    Get the ID of the wallet of a given name from the `kmd`.

    Args:
        kmd_client: the `kmd` client to query
        name: the wallet name

    Returns:
        the wallet ID in `kmd` or `None` if it is not found
    """
    wallets = {w["name"]: w for w in kmd_client.list_wallets()}
    wallet_id = wallets.get(name, {}).get("id", None)
    return wallet_id


@contextmanager
def get_wallet_handle(client: KMDClient, wallet_id: str, password: str) -> str:
    """
    Request `kmd` initialize a wallet handle, and release it when the context
    is closed.

    Args:
        client: the client
        wallet_id: the wallet id
        password: the wallet password
    """
    handle = client.init_wallet_handle(wallet_id, password)
    yield handle
    client.release_wallet_handle(handle)
