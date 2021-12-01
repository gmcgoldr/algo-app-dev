from typing import NamedTuple

import algosdk as ag
import pyteal as tl
import pytest
from algosdk.future.transaction import (
    ApplicationClearStateTxn,
    ApplicationCloseOutTxn,
    ApplicationDeleteTxn,
    ApplicationNoOpTxn,
    ApplicationOptInTxn,
)
from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient

from pyteal_utils import apps, transactions

MSG_REJECT = r".*transaction rejected by ApprovalProgram$"


def test_app_info_builds_from_result():
    result = {"application-index": 0}
    info = apps.AppInfo.from_result(result)
    assert info.app_id == 0
    assert info.address == "6X7XJO6FX3SHUK2OUL46QBQDSNO67RAFK6O73KJD4IVOMTSOIYANOIVWNU"


def test_extract_state_value_returns_value():
    assert apps.extract_state_value({"type": 1, "bytes": "YQ==", "uint": None}) == b"a"
    assert apps.extract_state_value({"type": 2, "bytes": b"", "uint": 1}) == 1


@pytest.fixture
def state() -> apps.State:
    return apps.State(
        [
            apps.State.KeyInfo("a", tl.Int, tl.Int(0)),
            apps.State.KeyInfo(b"\x00", tl.Int, None),
            apps.State.KeyInfo(b"123", tl.Bytes, None),
        ]
    )


def test_state_returns_key_info(state: apps.State):
    assert state.key_to_info("a").key == b"a"
    assert state.key_to_info(b"\x00").key == b"\x00"
    assert state.key_to_info(b"123").key == b"123"
    assert state.key_to_info("123").key == b"123"
    with pytest.raises(KeyError):
        assert state.key_to_info("0")

    keys = [i.key for i in state.key_infos()]
    assert keys == [b"a", b"\x00", b"123"]


def test_state_builds_schema(state: apps.State):
    schema = state.schema()
    assert schema.num_uints == 2
    assert schema.num_byte_slices == 1


def fund_account(
    algod_client: AlgodClient, kmd_client: KMDClient, num_wait: int
) -> transactions.AccountInfo:
    account, txid = transactions.fund_from_genesis(
        algod_client, kmd_client, ag.util.algos_to_microalgos(1000)
    )
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)
    return account


@pytest.fixture
def funded_account(
    algod_client: AlgodClient, kmd_client: KMDClient, num_wait: int
) -> transactions.AccountInfo:
    return fund_account(algod_client, kmd_client, num_wait)


def test_app_builder_default_app_creates(
    algod_client: AlgodClient, funded_account: transactions.AccountInfo, num_wait: int
):
    app = apps.AppBuilder()

    txn = app.create_txn(
        algod_client, funded_account.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    txn_info = transactions.get_confirmed_transaction(
        algod_client, txid, num_wait if num_wait else 1
    )
    app_info = apps.AppInfo.from_result(txn_info)

    assert app_info.app_id
    assert app_info.address


def test_app_builder_default_app_opts_in_and_clears(
    algod_client: AlgodClient, funded_account: transactions.AccountInfo, num_wait: int
):
    app = apps.AppBuilder()

    txn = app.create_txn(
        algod_client, funded_account.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    txn_info = transactions.get_confirmed_transaction(
        algod_client, txid, num_wait if num_wait else 1
    )
    app_info = apps.AppInfo.from_result(txn_info)

    txn = ApplicationOptInTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    account_info = algod_client.account_info(funded_account.address)
    app_ids = [a.get("id", None) for a in account_info.get("apps-local-state", [])]
    assert app_info.app_id in app_ids

    txn = ApplicationClearStateTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    account_info = algod_client.account_info(funded_account.address)
    app_ids = [a.get("id", None) for a in account_info.get("apps-local-state", [])]
    assert app_info.app_id not in app_ids


def test_app_builder_default_app_rejects_other(
    algod_client: AlgodClient, funded_account: transactions.AccountInfo, num_wait: int
):
    app = apps.AppBuilder()

    txn = app.create_txn(
        algod_client, funded_account.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    txn_info = transactions.get_confirmed_transaction(
        algod_client, txid, num_wait if num_wait else 1
    )
    app_info = apps.AppInfo.from_result(txn_info)

    txn = ApplicationDeleteTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    with pytest.raises(ag.error.AlgodHTTPError, match=MSG_REJECT):
        algod_client.send_transaction(txn.sign(funded_account.key))

    txn = app.update_txn(
        algod_client,
        funded_account.address,
        algod_client.suggested_params(),
        app_info.app_id,
    )
    with pytest.raises(ag.error.AlgodHTTPError, match=MSG_REJECT):
        algod_client.send_transaction(txn.sign(funded_account.key))

    txn = ApplicationCloseOutTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    with pytest.raises(ag.error.AlgodHTTPError, match=MSG_REJECT):
        algod_client.send_transaction(txn.sign(funded_account.key))

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    with pytest.raises(ag.error.AlgodHTTPError, match=MSG_REJECT):
        algod_client.send_transaction(txn.sign(funded_account.key))

    txn = ApplicationNoOpTxn(
        funded_account.address,
        algod_client.suggested_params(),
        app_info.app_id,
        ["invoke"],
    )
    with pytest.raises(ag.error.AlgodHTTPError, match=MSG_REJECT):
        algod_client.send_transaction(txn.sign(funded_account.key))


def test_app_builder_default_app_constructs_defaults(
    algod_client: AlgodClient, funded_account: transactions.AccountInfo, num_wait: int
):
    app = apps.AppBuilder(
        global_state=apps.StateGlobal([apps.State.KeyInfo("a", tl.Int, apps.ONE)]),
        local_state=apps.StateLocal(
            [apps.State.KeyInfo("b", tl.Bytes, tl.Bytes("abc"))]
        ),
    )

    txn = app.create_txn(
        algod_client, funded_account.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    txn_info = transactions.get_confirmed_transaction(
        algod_client, txid, num_wait if num_wait else 1
    )
    app_info = apps.AppInfo.from_result(txn_info)

    app_state = algod_client.application_info(app_info.app_id)
    assert apps.get_app_global_key(app_state, "a") == 1

    txn = ApplicationOptInTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    account_state = algod_client.account_info(funded_account.address)
    assert apps.get_app_local_key(account_state, app_info.app_id, "b") == b"abc"


@pytest.fixture
def stateful_app() -> apps.AppBuilder:
    gstate = apps.StateGlobal(
        [
            apps.State.KeyInfo("created", tl.Int, apps.ONE),
            apps.State.KeyInfo("updated", tl.Int, apps.ZERO),
            apps.State.KeyInfo("opted_in", tl.Int, apps.ZERO),
            apps.State.KeyInfo("closed", tl.Int, apps.ZERO),
            apps.State.KeyInfo("cleared", tl.Int, apps.ZERO),
            apps.State.KeyInfo("invoked_a", tl.Int, apps.ZERO),
            apps.State.KeyInfo("invoked_ab", tl.Int, apps.ZERO),
            apps.State.KeyInfo("invoked_default", tl.Int, apps.ZERO),
        ]
    )
    lstate = apps.StateLocal(
        [
            apps.State.KeyInfo("opted_in", tl.Int, apps.ZERO),
            apps.State.KeyInfo("invoked_a", tl.Int, apps.ZERO),
            apps.State.KeyInfo("invoked_ab", tl.Int, apps.ZERO),
            apps.State.KeyInfo("invoked_default", tl.Int, apps.ZERO),
        ]
    )

    return apps.AppBuilder(
        on_delete=tl.Return(apps.ONE),
        on_update=tl.Seq(
            gstate.set("updated", gstate.get("updated") + apps.ONE), tl.Return(apps.ONE)
        ),
        on_opt_in=tl.Seq(
            # build the local state
            lstate.constructor(),
            # then count the opted in
            gstate.set("opted_in", gstate.get("opted_in") + apps.ONE),
            lstate.set("opted_in", lstate.get("opted_in") + apps.ONE),
            tl.Return(apps.ONE),
        ),
        on_close_out=tl.Seq(
            gstate.set("closed", gstate.get("closed") + apps.ONE), tl.Return(apps.ONE)
        ),
        on_clear=tl.Seq(
            gstate.set("cleared", gstate.get("cleared") + apps.ONE), tl.Return(apps.ONE)
        ),
        invokations={
            "a": tl.Seq(
                gstate.set("invoked_a", gstate.get("invoked_a") + apps.ONE),
                lstate.set("invoked_a", lstate.get("invoked_a") + apps.ONE),
                tl.Return(apps.ONE),
            ),
            "ab": tl.Seq(
                gstate.set("invoked_ab", gstate.get("invoked_ab") + apps.ONE),
                lstate.set("invoked_ab", lstate.get("invoked_ab") + apps.ONE),
                tl.Return(apps.ONE),
            ),
        },
        on_no_op=tl.Seq(
            gstate.set("invoked_default", gstate.get("invoked_default") + apps.ONE),
            lstate.set("invoked_default", lstate.get("invoked_default") + apps.ONE),
            tl.Return(apps.ONE),
        ),
        global_state=gstate,
        local_state=lstate,
    )


def create_app(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
) -> apps.AppInfo:
    txn = stateful_app.create_txn(
        algod_client, funded_account.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    txn_info = transactions.get_confirmed_transaction(
        algod_client, txid, num_wait if num_wait else 1
    )
    return apps.AppInfo.from_result(txn_info)


def test_app_builder_create_constructs_and_returns(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 0
    assert apps.get_app_global_key(app_state, "opted_in") == 0
    assert apps.get_app_global_key(app_state, "closed") == 0
    assert apps.get_app_global_key(app_state, "cleared") == 0
    assert apps.get_app_global_key(app_state, "invoked_a") == 0
    assert apps.get_app_global_key(app_state, "invoked_ab") == 0
    assert apps.get_app_global_key(app_state, "invoked_default") == 0

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") is None
    # fmt: on


def test_app_builder_delete_is_called(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    account_state = algod_client.account_info(funded_account.address)

    txn = ApplicationDeleteTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    with pytest.raises(ag.error.AlgodHTTPError):
        _ = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") is None
    # fmt: on


def test_app_builder_update_is_called(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)

    # NOTE: this just replaces the programs with the same ones since it is
    # using the same `AppBuilder`.
    txn = stateful_app.update_txn(
        algod_client,
        funded_account.address,
        algod_client.suggested_params(),
        app_info.app_id,
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 1
    assert apps.get_app_global_key(app_state, "opted_in") == 0
    assert apps.get_app_global_key(app_state, "closed") == 0
    assert apps.get_app_global_key(app_state, "cleared") == 0
    assert apps.get_app_global_key(app_state, "invoked_a") == 0
    assert apps.get_app_global_key(app_state, "invoked_ab") == 0
    assert apps.get_app_global_key(app_state, "invoked_default") == 0

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") is None
    # fmt: on


def opt_in(
    client: AlgodClient, app_id: int, account: transactions.AccountInfo, num_wait: int
):
    txn = ApplicationOptInTxn(account.address, client.suggested_params(), app_id)
    txid = client.send_transaction(txn.sign(account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(client, txid, num_wait)


def test_app_builder_opt_in_updates_state(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account, num_wait)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 0
    assert apps.get_app_global_key(app_state, "opted_in") == 1
    assert apps.get_app_global_key(app_state, "closed") == 0
    assert apps.get_app_global_key(app_state, "cleared") == 0
    assert apps.get_app_global_key(app_state, "invoked_a") == 0
    assert apps.get_app_global_key(app_state, "invoked_ab") == 0
    assert apps.get_app_global_key(app_state, "invoked_default") == 0

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") == 1
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") == 0
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") == 0
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") == 0
    # fmt: on


def test_app_builder_close_updates_state(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account, num_wait)

    txn = ApplicationCloseOutTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 0
    assert apps.get_app_global_key(app_state, "opted_in") == 1
    assert apps.get_app_global_key(app_state, "closed") == 1
    assert apps.get_app_global_key(app_state, "cleared") == 0
    assert apps.get_app_global_key(app_state, "invoked_a") == 0
    assert apps.get_app_global_key(app_state, "invoked_ab") == 0
    assert apps.get_app_global_key(app_state, "invoked_default") == 0

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") is None
    # fmt: on


def test_app_builder_clear_updates_state(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account, num_wait)

    txn = ApplicationClearStateTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 0
    assert apps.get_app_global_key(app_state, "opted_in") == 1
    assert apps.get_app_global_key(app_state, "closed") == 0
    assert apps.get_app_global_key(app_state, "cleared") == 1
    assert apps.get_app_global_key(app_state, "invoked_a") == 0
    assert apps.get_app_global_key(app_state, "invoked_ab") == 0
    assert apps.get_app_global_key(app_state, "invoked_default") == 0

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") is None
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") is None
    # fmt: on


def test_app_builder_invokation_a_is_called(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account, num_wait)

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id, ["a"]
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 0
    assert apps.get_app_global_key(app_state, "opted_in") == 1
    assert apps.get_app_global_key(app_state, "closed") == 0
    assert apps.get_app_global_key(app_state, "cleared") == 0
    assert apps.get_app_global_key(app_state, "invoked_a") == 1
    assert apps.get_app_global_key(app_state, "invoked_ab") == 0
    assert apps.get_app_global_key(app_state, "invoked_default") == 0

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") == 1
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") == 1
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") == 0
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") == 0
    # fmt: on


def test_app_builder_invokation_ab_is_called(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account, num_wait)

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id, ["ab"]
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 0
    assert apps.get_app_global_key(app_state, "opted_in") == 1
    assert apps.get_app_global_key(app_state, "closed") == 0
    assert apps.get_app_global_key(app_state, "cleared") == 0
    assert apps.get_app_global_key(app_state, "invoked_a") == 0
    assert apps.get_app_global_key(app_state, "invoked_ab") == 1
    assert apps.get_app_global_key(app_state, "invoked_default") == 0

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") == 1
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") == 0
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") == 1
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") == 0
    # fmt: on


def test_app_builder_default_invokation_is_called(
    algod_client: AlgodClient,
    funded_account: transactions.AccountInfo,
    num_wait: int,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, num_wait, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account, num_wait)

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert apps.get_app_global_key(app_state, "created") == 1
    assert apps.get_app_global_key(app_state, "updated") == 0
    assert apps.get_app_global_key(app_state, "opted_in") == 1
    assert apps.get_app_global_key(app_state, "closed") == 0
    assert apps.get_app_global_key(app_state, "cleared") == 0
    assert apps.get_app_global_key(app_state, "invoked_a") == 0
    assert apps.get_app_global_key(app_state, "invoked_ab") == 0
    assert apps.get_app_global_key(app_state, "invoked_default") == 1

    assert apps.get_app_local_key(account_state, app_info.app_id, "opted_in") == 1
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_a") == 0
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_ab") == 0
    assert apps.get_app_local_key(account_state, app_info.app_id, "invoked_default") == 1
    # fmt: on


class MultiStateOut(NamedTuple):
    app_info_1: apps.AppInfo
    account_1: transactions.AccountInfo
    app_info_2: apps.AppInfo
    account_2: transactions.AccountInfo


@pytest.fixture
def multi_state(
    algod_client: AlgodClient,
    kmd_client: KMDClient,
    num_wait: int,
) -> MultiStateOut:
    account_1 = fund_account(algod_client, kmd_client, num_wait)
    account_2 = fund_account(algod_client, kmd_client, num_wait)

    # setup an app with a single global and local state value
    state_g2 = apps.StateGlobal([apps.State.KeyInfo("ga", tl.Int, apps.ONE)])
    state_l2 = apps.StateLocal([apps.State.KeyInfo("la", tl.Int, apps.ONE)])
    app_2 = apps.AppBuilder(
        global_state=state_g2,
        local_state=state_l2,
    )
    txn = app_2.create_txn(
        algod_client, account_2.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(account_2.key))
    txn_info = transactions.get_confirmed_transaction(
        algod_client, txid, num_wait if num_wait else 1
    )
    app_info_2 = apps.AppInfo.from_result(txn_info)

    # opt-in an account to that app
    txn = ApplicationOptInTxn(
        account_2.address, algod_client.suggested_params(), app_info_2.app_id
    )
    txid = algod_client.send_transaction(txn.sign(account_2.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    # the state of app_2, as seen by an external app (app_1)
    state_g2r = apps.StateGlobalExternal(
        [apps.State.KeyInfo("ga", tl.Int, apps.ONE)],
        tl.Int(app_info_2.app_id),
    )
    state_l2r = apps.StateLocalExternal(
        [apps.State.KeyInfo("la", tl.Int, apps.ONE)],
        tl.Int(app_info_2.app_id),
        tl.Addr(account_2.address),
    )

    # setup an app with default and non-default global and local state
    state_g1 = apps.StateGlobal(
        [
            apps.State.KeyInfo("ga", tl.Int, apps.ONE),
            apps.State.KeyInfo("gb", tl.Bytes, None),
        ]
    )
    state_l1 = apps.StateLocal(
        [
            apps.State.KeyInfo("la", tl.Int, apps.ONE),
            apps.State.KeyInfo("lb", tl.Bytes, None),
        ]
    )
    # allow manipulating the state using invokations
    app_1 = apps.AppBuilder(
        invokations={
            "set_gb": tl.Seq(
                state_g1.set("gb", tl.Txn.application_args[1]),
                tl.Return(apps.ONE),
            ),
            "set_lb": tl.Seq(
                state_l1.set("lb", tl.Txn.application_args[1]),
                tl.Return(apps.ONE),
            ),
            "get_ga": tl.Return(state_g1.get("ga")),
            "get_has_gb": tl.Return(state_g1.load_ex_has_value("gb")),
            "get_gb_cmp": tl.Return(
                state_g1.load_ex_value("gb") == tl.Txn.application_args[1]
            ),
            "get_la": tl.Return(state_l1.get("la")),
            "get_has_lb": tl.Return(state_l1.load_ex_has_value("lb")),
            "get_lb_cmp": tl.Return(
                state_l1.load_ex_value("lb") == tl.Txn.application_args[1]
            ),
            # NOTE: these experssions are loading into an external app
            "get_ga2": tl.Return(state_g2r.load_ex_value("ga")),
            "get_la2": tl.Return(state_l2r.load_ex_value("la")),
        },
        global_state=state_g1,
        local_state=state_l1,
    )
    txn = app_1.create_txn(
        algod_client, account_1.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(account_1.key))
    txn_info = transactions.get_confirmed_transaction(
        algod_client, txid, num_wait if num_wait else 1
    )
    app_info_1 = apps.AppInfo.from_result(txn_info)

    # opt-in the other account
    txn = ApplicationOptInTxn(
        account_1.address, algod_client.suggested_params(), app_info_1.app_id
    )
    txid = algod_client.send_transaction(txn.sign(account_1.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    return MultiStateOut(app_info_1, account_1, app_info_2, account_2)


def test_state_can_get_global_value(
    algod_client: AlgodClient, multi_state: MultiStateOut
):
    app_info_1, account_1, _, _ = multi_state
    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_ga"],
    )
    # passes because ga1 is set to 1
    _ = algod_client.send_transaction(txn.sign(account_1.key))


def test_state_can_manipulate_global_maybe_value(
    algod_client: AlgodClient, num_wait: int, multi_state: MultiStateOut
):
    app_info_1, account_1, _, _ = multi_state

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_has_gb"],
    )
    # doesn't have a value set for gb
    with pytest.raises(ag.error.AlgodHTTPError, match=MSG_REJECT):
        _ = algod_client.send_transaction(txn.sign(account_1.key))

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["set_gb", b"abc"],
    )
    # set to some bytes
    txid = algod_client.send_transaction(txn.sign(account_1.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_has_gb"],
    )
    # has value
    _ = algod_client.send_transaction(txn.sign(account_1.key))

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_gb_cmp", b"abc"],
    )
    # confirm the value
    _ = algod_client.send_transaction(txn.sign(account_1.key))


def test_state_can_get_global_foreign_value(
    algod_client: AlgodClient, multi_state: MultiStateOut
):
    app_info_1, account_1, app_info_2, account_2 = multi_state

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_ga2"],
        accounts=[account_2.address],
        foreign_apps=[app_info_2.app_id],
    )
    # passes because ga2 is set to 1, not the same state as ga1
    _ = algod_client.send_transaction(txn.sign(account_1.key))


def test_state_can_get_local_value(
    algod_client: AlgodClient, multi_state: MultiStateOut
):
    app_info_1, account_1, _, _ = multi_state
    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_la"],
    )
    # passes because ga1 is set to 1
    _ = algod_client.send_transaction(txn.sign(account_1.key))


def test_state_can_manipulate_local_maybe_value(
    algod_client: AlgodClient, num_wait: int, multi_state: MultiStateOut
):
    app_info_1, account_1, _, _ = multi_state

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_has_lb"],
    )
    # doesn't have a value set for gb
    with pytest.raises(ag.error.AlgodHTTPError, match=MSG_REJECT):
        _ = algod_client.send_transaction(txn.sign(account_1.key))

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["set_lb", b"abc"],
    )
    # set to some bytes
    txid = algod_client.send_transaction(txn.sign(account_1.key))
    if num_wait:
        _ = transactions.get_confirmed_transaction(algod_client, txid, num_wait)

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_has_lb"],
    )
    # has value
    _ = algod_client.send_transaction(txn.sign(account_1.key))

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_lb_cmp", b"abc"],
    )
    # confirm the value
    _ = algod_client.send_transaction(txn.sign(account_1.key))


def test_state_can_get_local_foreign_value(
    algod_client: AlgodClient, multi_state: MultiStateOut
):
    app_info_1, account_1, app_info_2, account_2 = multi_state

    txn = ApplicationNoOpTxn(
        account_1.address,
        algod_client.suggested_params(),
        app_info_1.app_id,
        app_args=["get_la2"],
        accounts=[account_2.address],
        foreign_apps=[app_info_2.app_id],
    )
    # passes because ga2 is set to 1, not the same state as ga1
    _ = algod_client.send_transaction(txn.sign(account_1.key))
