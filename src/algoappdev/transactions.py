from typing import Dict, List, Tuple

import algosdk as ag
from algosdk.future import transaction
from algosdk.future.transaction import PaymentTxn
from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient
from algosdk.wallet import Wallet

from .utils import AccountMeta


def get_confirmed_transactions(
    client: AlgodClient, transaction_ids: List[int], timeout_blocks: int
) -> Dict:
    """
    Wait for the network to confirm some transactions and return their info.

    Args:
        client: the client
        transaction_ids: list of transactions for which to retreive info
        timeout_blocks: wait for this many blocks to confirm the transactions

    Returns:
        list of transaction info for confirmed transactions
    """
    start_round = client.status()["last-round"] + 1
    current_round = start_round

    # the transaction ids that are not yet confirmed
    waiting_ids = set(transaction_ids)
    # list of transaction info for confirmed transactions
    infos = []

    while current_round < start_round + timeout_blocks:
        for transaction_id in list(waiting_ids):
            # NOTE: documentation suggests that transactions are "remembered"
            # by a node for some time after confirmation, but doesn't specify
            # how long
            pending_txn = client.pending_transaction_info(transaction_id)
            if pending_txn["pool-error"]:
                waiting_ids.remove(transaction_id)
            elif pending_txn.get("confirmed-round", 0) > 0:
                infos.append(pending_txn)
                waiting_ids.remove(transaction_id)
        if not waiting_ids:
            break
        # wait until the end of this block
        client.status_after_block(current_round)
        current_round += 1

    return infos


def get_confirmed_transaction(
    client: AlgodClient, transaction_id: int, timeout_blocks: int
) -> Dict:
    """
    See `get_confirmed_transactions`, but for a single transaction id.
    """
    confirmed = get_confirmed_transactions(client, [transaction_id], timeout_blocks)
    if confirmed:
        return confirmed[0]
    else:
        return None


def fund_from_genesis(
    algod_client: AlgodClient, kmd_client: KMDClient, amount: int
) -> Tuple[AccountMeta, str]:
    """
    Create a new account and fund it from the account that received the gensis
    funds.

    Expects an unencrypted wallet "unencrypted-default-wallet" whose first key
    is the address of the account with the genesis funds.

    Args:
        algod_client: client to send node commands to
        kmd_client: client to use in signing the transaction
        amount: the quantity of microAlgos to fund

    Returns:
        the funded account info, and funding transaction id
    """
    wallet = Wallet("unencrypted-default-wallet", "", kmd_client)
    sender_address = wallet.list_keys()[0]

    receiver = AccountMeta(*ag.account.generate_account())

    # Transfer algos to the escrow account
    params = algod_client.suggested_params()
    params.fee = 0  # use the minimum network fee
    txn = PaymentTxn(
        sender=sender_address, sp=params, receiver=receiver.address, amt=amount
    )
    txn = wallet.sign_transaction(txn)
    txid = algod_client.send_transaction(txn)

    return receiver, txid


def group_txns(*txns: transaction.Transaction) -> List[transaction.Transaction]:
    """
    Group multiple transactions.

    Args:
        txns: the transactions to group

    Returns:
        list of transactions, with the `group` memmber set
    """
    gid = transaction.calculate_group_id(txns)
    for txn in txns:
        txn.group = gid
    return txns


def pad_lease_bytes(lease: bytes) -> bytes:
    """
    Given a string of bytes to use as a lease, right pad with 0s to get the
    correct number of bytes.
    """
    lease = lease[: ag.constants.LEASE_LENGTH]
    lease = lease + (b"\x00" * max(0, ag.constants.LEASE_LENGTH - len(lease)))
    return lease
