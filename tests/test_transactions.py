import algosdk as ag
from algosdk.future.transaction import PaymentTxn
from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient

from algoappdev import transactions
from algoappdev.testing import WAIT_ROUNDS
from algoappdev.utils import AccountMeta


def test_fund_from_genesis_funds_new_account(
    algod_client: AlgodClient, kmd_client: KMDClient
):
    account, txid = transactions.fund_from_genesis(
        algod_client, kmd_client, ag.util.algos_to_microalgos(1000)
    )
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)
    assert algod_client.account_info(account.address).get(
        "amount"
    ) == ag.util.algos_to_microalgos(1000)


def test_get_confirmed_transaction_returns_info(
    algod_client: AlgodClient, kmd_client: KMDClient
):
    account1, txid = transactions.fund_from_genesis(
        algod_client, kmd_client, ag.util.algos_to_microalgos(1000)
    )
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)
    account2 = AccountMeta(*ag.account.generate_account())

    params = algod_client.suggested_params()

    txn = PaymentTxn(
        sender=account1.address,
        sp=params,
        receiver=account2.address,
        amt=ag.util.algos_to_microalgos(1),
    )
    txn = txn.sign(account1.key)
    txid = algod_client.send_transaction(txn)

    info = transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)
    assert info.get("confirmed-round")
    assert not info.get("pool-error")
    assert info.get("txn", {}).get("txn", {}).get(
        "amt", None
    ) == ag.util.algos_to_microalgos(1)


def test_groups_transactions(algod_client: AlgodClient):
    account1 = AccountMeta(*ag.account.generate_account())
    account2 = AccountMeta(*ag.account.generate_account())

    params = algod_client.suggested_params()

    txn1 = PaymentTxn(
        sender=account1.address,
        sp=params,
        receiver=account2.address,
        amt=ag.util.algos_to_microalgos(1),
    )
    txn2 = PaymentTxn(
        sender=account2.address,
        sp=params,
        receiver=account1.address,
        amt=ag.util.algos_to_microalgos(1),
    )

    txns = transactions.group_txns(txn1, txn2)

    assert txns[0].group is not None
    assert txns[0].group == txns[1].group


def test_pad_lease_bytes_pads():
    n = ag.constants.LEASE_LENGTH
    assert transactions.pad_lease_bytes(b"ab") == b"ab" + (b"\x00" * (n - 2))


def test_pad_lease_bytes_truncates():
    n = ag.constants.LEASE_LENGTH
    assert transactions.pad_lease_bytes(b"a" * (n + 1)) == b"a" * n
