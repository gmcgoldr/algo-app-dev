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
from algosdk.v2client.models.application_state_schema import ApplicationStateSchema
from algosdk.v2client.models.teal_key_value import TealKeyValue

from algoappdev import apps
from algoappdev import dryruns as dr
from algoappdev import transactions, utils
from algoappdev.clients import get_app_global_key, get_app_local_key
from algoappdev.testing import WAIT_ROUNDS, fund_account
from algoappdev.utils import (
    ZERO_ADDRESS,
    AccountMeta,
    AppMeta,
    idx_to_address,
    to_key_value,
)

MSG_REJECT = r".*transaction rejected by ApprovalProgram$"


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
    assert state.key_info("a").key == b"a"
    assert state.key_info(b"\x00").key == b"\x00"
    assert state.key_info(b"123").key == b"123"
    assert state.key_info("123").key == b"123"
    with pytest.raises(KeyError):
        assert state.key_info("0")

    keys = [i.key for i in state.key_infos()]
    assert keys == [b"a", b"\x00", b"123"]


def test_state_builds_schema(state: apps.State):
    schema = state.schema()
    assert schema.num_uints == 2
    assert schema.num_byte_slices == 1


def test_app_builder_builds_application(algod_client: AlgodClient):
    address = utils.idx_to_address(1)
    app = apps.AppBuilder().build_application(
        algod_client, 123, address, [to_key_value(b"abc", 234)]
    )
    assert app.id == 123
    assert app.params.creator == address
    assert app.params.approval_program
    assert app.params.clear_state_program
    assert app.params.global_state_schema == ApplicationStateSchema()
    assert app.params.local_state_schema == ApplicationStateSchema()
    assert app.params.global_state == [to_key_value(b"abc", 234)]


def test_app_builder_default_app_creates(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        # NOTE: must set creator for `ApplicationCreateTxn`
        .with_app(builder.build_application(algod_client, 1, ZERO_ADDRESS))
        .with_txn(
            builder.create_txn(
                algod_client, ZERO_ADDRESS, dr.AppCallCtx().suggested_params()
            )
        )
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "PASS"]


def test_app_builder_default_app_opts_in(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_txn_call(dr.OnComplete.OptInOC)
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "PASS"]


def test_app_builder_default_app_clears(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_account_opted_in()
        .with_txn_call(dr.OnComplete.ClearStateOC)
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ClearStateProgram", "PASS"]


def test_app_builder_default_app_does_not_close_out(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_account_opted_in()
        .with_txn_call(dr.OnComplete.CloseOutOC)
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "REJECT"]


def test_app_builder_default_app_does_not_no_op(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_txn_call()
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "REJECT"]


def test_app_builder_default_app_does_not_no_op_args(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_txn_call(args=[b"abc"])
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "REJECT"]


def test_app_builder_default_app_does_not_update(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_txn(
            builder.update_txn(
                algod_client, ZERO_ADDRESS, dr.AppCallCtx().suggested_params(), 1
            )
        )
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "REJECT"]


def test_app_builder_default_app_does_not_delete(algod_client: AlgodClient):
    builder = apps.AppBuilder()
    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_account_opted_in()
        .with_txn_call(dr.OnComplete.DeleteApplicationOC)
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "REJECT"]


def test_app_builder_default_app_constructs_defaults(algod_client: AlgodClient):
    builder = apps.AppBuilder(
        global_state=apps.StateGlobal([apps.State.KeyInfo("a", tl.Int, apps.ONE)]),
        local_state=apps.StateLocal(
            [apps.State.KeyInfo("b", tl.Bytes, tl.Bytes("abc"))]
        ),
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1, ZERO_ADDRESS))
        .with_txn(
            builder.create_txn(
                algod_client, ZERO_ADDRESS, dr.AppCallCtx().suggested_params()
            )
        )
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "PASS"]
    assert dr.get_global_deltas(result) == [dr.KeyDelta(b"a", 1)]

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_account(dr.build_account(ZERO_ADDRESS))
        .with_txn_call(dr.OnComplete.OptInOC)
        .build_request()
    )
    messages = dr.get_messages(result)
    assert messages == ["ApprovalProgram", "PASS"]
    assert dr.get_local_deltas(result) == {ZERO_ADDRESS: [dr.KeyDelta(b"b", b"abc")]}


def test_state_global_gets_value(algod_client: AlgodClient):
    state = apps.StateGlobal([apps.State.KeyInfo("abc", tl.Int)])
    builder = apps.AppBuilder(
        invocations={"get_abc": tl.Return(state.get("abc"))},
        global_state=state,
    )

    app = builder.build_application(algod_client, 1)
    app.params.global_state = [to_key_value(state.key_info("abc").key, 123)]
    result = algod_client.dryrun(
        dr.AppCallCtx().with_app(app).with_txn_call(args=["get_abc"]).build_request()
    )
    dr.check_err(result)
    # return value is 123
    assert dr.get_trace(result)[-1].stack == [123]


def test_state_global_sets_value(algod_client: AlgodClient):
    state = apps.StateGlobal([apps.State.KeyInfo("abc", tl.Int)])
    builder = apps.AppBuilder(
        invocations={
            "set_abc": tl.Seq(
                state.set("abc", tl.Btoi(tl.Txn.application_args[1])),
                tl.Return(apps.ONE),
            )
        },
        global_state=state,
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_txn_call(args=["set_abc", 123])
        .build_request()
    )
    dr.check_err(result)
    assert dr.get_global_deltas(result) == [dr.KeyDelta(b"abc", 123)]


def test_state_global_drops_value(algod_client: AlgodClient):
    state = apps.StateGlobal([apps.State.KeyInfo("abc", tl.Int)])
    builder = apps.AppBuilder(
        invocations={"drop_abc": tl.Seq(state.drop("abc"), tl.Return(apps.ONE))},
        global_state=state,
    )

    app = builder.build_application(algod_client, 1)
    app.params.global_state = [to_key_value(state.key_info("abc").key, 123)]
    result = algod_client.dryrun(
        dr.AppCallCtx().with_app(app).with_txn_call(args=["drop_abc"]).build_request()
    )
    dr.check_err(result)
    assert dr.get_global_deltas(result) == [dr.KeyDelta(b"abc", None)]


@pytest.mark.skip(reason="foreign apps not working in dryruns")
def test_state_global_gets_external_value(algod_client: AlgodClient):
    state_ex = apps.StateGlobalExternal([apps.State.KeyInfo("abc", tl.Int)], tl.Int(1))
    # this app has no state, but can access another app's state
    builder = apps.AppBuilder(
        invocations={"get_abc": tl.Return(state_ex.load_ex_value("abc"))},
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        # the external app,
        .with_app_program(
            app_idx=1, state=[to_key_value(state_ex.key_info("abc").key, 123)]
        )
        # the app to execute
        .with_app(builder.build_application(algod_client, app_idx=2))
        .with_txn_call(args=["get_abc"])
        .build_request()
    )
    dr.check_err(result)
    # return value is 123
    assert dr.get_trace(result)[-1].stack == [123]


def test_state_local_gets_value_sender(algod_client: AlgodClient):
    state = apps.StateLocal([apps.State.KeyInfo("abc", tl.Int)])
    builder = apps.AppBuilder(
        invocations={"get_abc": tl.Return(state.get("abc"))},
        local_state=state,
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_account_opted_in(
            local_state=[to_key_value(state.key_info("abc").key, 123)]
        )
        .with_txn_call(args=["get_abc"])
        .build_request()
    )
    dr.check_err(result)
    # return value is 123
    assert dr.get_trace(result)[-1].stack == [123]


def test_state_local_gets_value_other(algod_client: AlgodClient):
    address_1 = idx_to_address(1)
    address_2 = idx_to_address(2)

    state = apps.StateLocal([apps.State.KeyInfo("abc", tl.Int)], tl.Addr(address_2))
    builder = apps.AppBuilder(
        invocations={"get_abc": tl.Return(state.get("abc"))},
        local_state=state,
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        # account 2 contains the local state
        .with_account_opted_in(
            address=address_2,
            local_state=[to_key_value(state.key_info("abc").key, 123)],
        )
        # account 1 is calling the app
        .with_account_opted_in(address=address_1)
        .with_txn_call(args=["get_abc"])
        .build_request()
    )
    dr.check_err(result)
    # return value is 123
    assert dr.get_trace(result)[-1].stack == [123]


def test_state_local_sets_value_sender(algod_client: AlgodClient):
    address = idx_to_address(1)

    state = apps.StateLocal([apps.State.KeyInfo("abc", tl.Int)])
    builder = apps.AppBuilder(
        invocations={
            "set_abc": tl.Seq(state.set("abc", tl.Int(123)), tl.Return(apps.ONE))
        },
        local_state=state,
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_account_opted_in(address=address)
        .with_txn_call(args=["set_abc"])
        .build_request()
    )
    dr.check_err(result)
    assert dr.get_local_deltas(result) == {address: [dr.KeyDelta(b"abc", 123)]}


def test_state_local_drops_value_sender(algod_client: AlgodClient):
    address = idx_to_address(1)

    state = apps.StateLocal([apps.State.KeyInfo("abc", tl.Int)])
    builder = apps.AppBuilder(
        invocations={"drop_abc": tl.Seq(state.drop("abc"), tl.Return(apps.ONE))},
        local_state=state,
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        .with_account_opted_in(
            address=address, local_state=[to_key_value(state.key_info("abc").key, 123)]
        )
        .with_txn_call(args=["drop_abc"])
        .build_request()
    )
    dr.check_err(result)
    assert dr.get_local_deltas(result) == {address: [dr.KeyDelta(b"abc", None)]}


def test_state_local_sets_value_other(algod_client: AlgodClient):
    address_1 = idx_to_address(1)
    address_2 = idx_to_address(2)

    state = apps.StateLocal([apps.State.KeyInfo("abc", tl.Int)], tl.Addr(address_2))
    builder = apps.AppBuilder(
        invocations={
            "set_abc": tl.Seq(state.set("abc", tl.Int(123)), tl.Return(apps.ONE))
        },
        local_state=state,
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        .with_app(builder.build_application(algod_client, 1))
        # account 2 will get the local state
        .with_account_opted_in(address=address_2)
        # account 1 is calling the app
        .with_account_opted_in(address=address_1)
        .with_txn_call(args=["set_abc"])
        .build_request()
    )
    dr.check_err(result)
    assert dr.get_local_deltas(result) == {address_2: [dr.KeyDelta(b"abc", 123)]}


@pytest.mark.skip(reason="foreign apps not working in dryruns")
def test_state_local_gets_external_value(algod_client: AlgodClient):
    address_1 = idx_to_address(1)
    address_2 = idx_to_address(2)

    state_ex = apps.StateLocalExternal(
        [apps.State.KeyInfo("abc", tl.Int)], tl.Int(1), address_2
    )
    # this app has no state, but can access another app's state
    builder = apps.AppBuilder(
        invocations={"get_abc": tl.Return(state_ex.load_ex_value("abc"))},
    )

    result = algod_client.dryrun(
        dr.AppCallCtx()
        # the external app,
        .with_app_program(app_idx=1)
        # account with local state for that app
        .with_account_opted_in(
            address=address_2,
            local_state=[to_key_value(state_ex.key_info("abc").key, 123)],
        )
        # the app to execute
        .with_app(builder.build_application(algod_client, app_idx=2))
        # caller is different
        .with_account_opted_in(address=address_1)
        .with_txn_call(args=["set_abc"])
        .build_request()
    )
    dr.check_err(result)
    # return value is 123
    assert dr.get_trace(result)[-1].stack == [123]


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
        invocations={
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
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
) -> AppMeta:
    txn = stateful_app.create_txn(
        algod_client, funded_account.address, algod_client.suggested_params()
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    txn_info = transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)
    return AppMeta.from_result(txn_info)


def test_app_builder_create_constructs_and_returns(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 0
    assert get_app_global_key(app_state, b"opted_in") == 0
    assert get_app_global_key(app_state, b"closed") == 0
    assert get_app_global_key(app_state, b"cleared") == 0
    assert get_app_global_key(app_state, b"invoked_a") == 0
    assert get_app_global_key(app_state, b"invoked_ab") == 0
    assert get_app_global_key(app_state, b"invoked_default") == 0

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") is None
    # fmt: on


def test_app_builder_delete_is_called(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    account_state = algod_client.account_info(funded_account.address)

    txn = ApplicationDeleteTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

    with pytest.raises(ag.error.AlgodHTTPError):
        algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") is None
    # fmt: on


def test_app_builder_update_is_called(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)

    # NOTE: this just replaces the programs with the same ones since it is
    # using the same `AppBuilder`.
    txn = stateful_app.update_txn(
        algod_client,
        funded_account.address,
        algod_client.suggested_params(),
        app_info.app_id,
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 1
    assert get_app_global_key(app_state, b"opted_in") == 0
    assert get_app_global_key(app_state, b"closed") == 0
    assert get_app_global_key(app_state, b"cleared") == 0
    assert get_app_global_key(app_state, b"invoked_a") == 0
    assert get_app_global_key(app_state, b"invoked_ab") == 0
    assert get_app_global_key(app_state, b"invoked_default") == 0

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") is None
    # fmt: on


def opt_in(client: AlgodClient, app_id: int, account: AccountMeta):
    txn = ApplicationOptInTxn(account.address, client.suggested_params(), app_id)
    txid = client.send_transaction(txn.sign(account.key))
    transactions.get_confirmed_transaction(client, txid, WAIT_ROUNDS)


def test_app_builder_opt_in_updates_state(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 0
    assert get_app_global_key(app_state, b"opted_in") == 1
    assert get_app_global_key(app_state, b"closed") == 0
    assert get_app_global_key(app_state, b"cleared") == 0
    assert get_app_global_key(app_state, b"invoked_a") == 0
    assert get_app_global_key(app_state, b"invoked_ab") == 0
    assert get_app_global_key(app_state, b"invoked_default") == 0

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") == 1
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") == 0
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") == 0
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") == 0
    # fmt: on


def test_app_builder_close_updates_state(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account)

    txn = ApplicationCloseOutTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 0
    assert get_app_global_key(app_state, b"opted_in") == 1
    assert get_app_global_key(app_state, b"closed") == 1
    assert get_app_global_key(app_state, b"cleared") == 0
    assert get_app_global_key(app_state, b"invoked_a") == 0
    assert get_app_global_key(app_state, b"invoked_ab") == 0
    assert get_app_global_key(app_state, b"invoked_default") == 0

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") is None
    # fmt: on


def test_app_builder_clear_updates_state(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account)

    txn = ApplicationClearStateTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 0
    assert get_app_global_key(app_state, b"opted_in") == 1
    assert get_app_global_key(app_state, b"closed") == 0
    assert get_app_global_key(app_state, b"cleared") == 1
    assert get_app_global_key(app_state, b"invoked_a") == 0
    assert get_app_global_key(app_state, b"invoked_ab") == 0
    assert get_app_global_key(app_state, b"invoked_default") == 0

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") is None
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") is None
    # fmt: on


def test_app_builder_invocation_a_is_called(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account)

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id, ["a"]
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 0
    assert get_app_global_key(app_state, b"opted_in") == 1
    assert get_app_global_key(app_state, b"closed") == 0
    assert get_app_global_key(app_state, b"cleared") == 0
    assert get_app_global_key(app_state, b"invoked_a") == 1
    assert get_app_global_key(app_state, b"invoked_ab") == 0
    assert get_app_global_key(app_state, b"invoked_default") == 0

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") == 1
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") == 1
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") == 0
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") == 0
    # fmt: on


def test_app_builder_invocation_ab_is_called(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account)

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id, ["ab"]
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 0
    assert get_app_global_key(app_state, b"opted_in") == 1
    assert get_app_global_key(app_state, b"closed") == 0
    assert get_app_global_key(app_state, b"cleared") == 0
    assert get_app_global_key(app_state, b"invoked_a") == 0
    assert get_app_global_key(app_state, b"invoked_ab") == 1
    assert get_app_global_key(app_state, b"invoked_default") == 0

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") == 1
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") == 0
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") == 1
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") == 0
    # fmt: on


def test_app_builder_default_invocation_is_called(
    algod_client: AlgodClient,
    funded_account: AccountMeta,
    stateful_app: apps.AppBuilder,
):
    app_info = create_app(algod_client, funded_account, stateful_app)
    opt_in(algod_client, app_info.app_id, funded_account)

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_info.app_id
    )
    txid = algod_client.send_transaction(txn.sign(funded_account.key))
    transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

    app_state = algod_client.application_info(app_info.app_id)
    account_state = algod_client.account_info(funded_account.address)

    # fmt: off
    assert get_app_global_key(app_state, b"created") == 1
    assert get_app_global_key(app_state, b"updated") == 0
    assert get_app_global_key(app_state, b"opted_in") == 1
    assert get_app_global_key(app_state, b"closed") == 0
    assert get_app_global_key(app_state, b"cleared") == 0
    assert get_app_global_key(app_state, b"invoked_a") == 0
    assert get_app_global_key(app_state, b"invoked_ab") == 0
    assert get_app_global_key(app_state, b"invoked_default") == 1

    assert get_app_local_key(account_state, app_info.app_id, b"opted_in") == 1
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_a") == 0
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_ab") == 0
    assert get_app_local_key(account_state, app_info.app_id, b"invoked_default") == 1
    # fmt: on
