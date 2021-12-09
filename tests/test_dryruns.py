import algosdk as ag
import pyteal as tl
import pytest
from algosdk.future.transaction import OnComplete
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.models.application_local_state import ApplicationLocalState
from algosdk.v2client.models.application_state_schema import ApplicationStateSchema

from algoappdev import apps, dryruns, utils
from algoappdev.utils import AlgoAppDevError, idx_to_address, to_key_value


def test_build_application_uses_defaults():
    app = dryruns.build_application(1)
    assert app.id == 1
    assert app.params.creator is None
    assert app.params.approval_program is None
    assert app.params.clear_state_program is None
    assert app.params.global_state_schema == dryruns.MAX_SCHEMA
    assert app.params.local_state_schema == dryruns.MAX_SCHEMA


def test_build_application_passes_arguments():
    app = dryruns.build_application(
        1,
        b"approval",
        b"clear",
        ApplicationStateSchema(1, 2),
        ApplicationStateSchema(2, 3),
        ["state"],
        b"creator",
    )
    assert app.id == 1
    assert app.params.creator == b"creator"
    assert app.params.approval_program == b"approval"
    assert app.params.clear_state_program == b"clear"
    assert app.params.global_state_schema == ApplicationStateSchema(1, 2)
    assert app.params.local_state_schema == ApplicationStateSchema(2, 3)


def test_build_account_uses_defaults():
    account = dryruns.build_account("address")
    assert account.address == "address"
    assert account.amount is None
    assert account.apps_local_state is None
    assert account.assets is None
    assert account.status == "Offline"


def test_build_account_passes_arguments():
    account = dryruns.build_account("address", ["state"], ["asset"], 123, "status")
    assert account.address == "address"
    assert account.amount == 123
    assert account.apps_local_state == ["state"]
    assert account.assets == ["asset"]
    assert account.status == "status"


def test_suggested_params_uses_defaults():
    params = dryruns.AppCallCtx().suggested_params()
    assert params.first == 1
    assert params.last == 1000
    assert params.fee == ag.constants.min_txn_fee
    assert params.flat_fee
    assert not params.gh


def test_suggested_params_uses_round():
    params = dryruns.AppCallCtx().with_round(123).suggested_params()
    assert params.first == 123
    assert params.last == 1122


def test_with_app_program_uses_defaults():
    ctx = dryruns.AppCallCtx().with_app_program()
    assert ctx.apps
    assert ctx.apps[0].id == 1
    assert ctx.apps[0].params.global_state_schema == dryruns.MAX_SCHEMA
    assert ctx.apps[0].params.local_state_schema == dryruns.MAX_SCHEMA


def test_with_app_program_passes_arguments():
    ctx = dryruns.AppCallCtx().with_app_program(
        program=b"code", app_idx=123, state=["state"]
    )
    assert ctx.apps
    assert ctx.apps[0].id == 123
    assert ctx.apps[0].params.approval_program == b"code"
    assert ctx.apps[0].params.global_state == ["state"]


def test_with_account_opted_in_uses_defaults():
    ctx = (
        dryruns.AppCallCtx()
        .with_app_program()
        .with_app_program()
        .with_account_opted_in()
    )
    assert ctx.accounts
    # starts addresses at 1
    assert ctx.accounts[0].address == idx_to_address(1)
    # automatically opted into last account
    assert ctx.accounts[0].apps_local_state == [ApplicationLocalState(2)]


def test_with_account_opted_in_passes_arguments():
    ctx = dryruns.AppCallCtx().with_account_opted_in(
        123, idx_to_address(234), ["state"]
    )
    assert ctx.accounts
    assert ctx.accounts[0].address == idx_to_address(234)
    assert ctx.accounts[0].apps_local_state == [
        ApplicationLocalState(123, key_value=["state"])
    ]


def test_with_txn_call_uses_defaults():
    ctx = (
        dryruns.AppCallCtx().with_app_program().with_account_opted_in().with_txn_call()
    )
    assert ctx.txns
    assert ctx.txns[0].sender == ctx.accounts[0].address
    assert ctx.txns[0].index == ctx.apps[0].id
    assert ctx.txns[0].on_complete == OnComplete.NoOpOC
    assert ctx.txns[0].accounts == [ctx.accounts[0].address]
    assert ctx.txns[0].foreign_apps == [ctx.apps[0].id]
    assert ctx.txns[0].foreign_assets == None


def test_with_txn_call_passes_arguments():
    ctx = (
        dryruns.AppCallCtx()
        .with_app_program()
        .with_account_opted_in()
        .with_txn_call(OnComplete.OptInOC, sender=idx_to_address(123), app_idx=123)
    )
    assert ctx.txns
    assert ctx.txns[0].sender == idx_to_address(123)
    assert ctx.txns[0].index == 123
    assert ctx.txns[0].on_complete == OnComplete.OptInOC
    assert ctx.txns[0].accounts == [ctx.accounts[0].address]
    assert ctx.txns[0].foreign_apps == [ctx.apps[0].id]
    assert ctx.txns[0].foreign_assets == None


def test_check_err_raises_error():
    result = {"error": "message"}
    with pytest.raises(AlgoAppDevError, match="message"):
        dryruns.check_err(result)


def test_get_messages_returns_message_for_transaction():
    result = {"txns": [None, {"app-call-messages": ["a", "b"]}]}
    assert dryruns.get_messages(result, 1) == ["a", "b"]


def test_context_with_nothing_does_nothing(algod_client: AlgodClient):
    result = algod_client.dryrun(dryruns.AppCallCtx().build_request())
    dryruns.check_err(result)


def test_context_txn_with_no_app_does_not_run(algod_client: AlgodClient):
    result = algod_client.dryrun(dryruns.AppCallCtx().with_txn_call().build_request())
    assert len(result.get("txns", [])) == 1
    assert result["txns"][0]["disassembly"] is None


def test_context_txn_calls_program(algod_client: AlgodClient):
    logic = tl.Return(tl.Int(1))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_txn_call()
        .build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


def test_context_txn_accesses_args(algod_client: AlgodClient):
    logic = tl.Return(tl.Txn.application_args[0] == tl.Bytes("abc"))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_txn_call(args=[b"abc"])
        .build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


def test_context_txn_accesses_program(algod_client: AlgodClient):
    logic = tl.Return(tl.App.globalGet(tl.Bytes("abc")) == tl.Int(123))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(
            apps.compile_source(algod_client, apps.compile_expr(logic)),
            state=[to_key_value(b"abc", 123)],
        )
        .with_txn_call()
        .build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


@pytest.mark.skip(reason="FIXME: algod is doesn't see the foreign app")
def test_context_txn_accesses_multiple_programs(algod_client: AlgodClient):
    value = tl.App.globalGetEx(tl.Txn.applications[1], tl.Bytes("abc"))
    logic = tl.Return(tl.Seq(value, value.value() == tl.Int(123)))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        # this app can't be called because it has no program
        .with_app(
            dryruns.build_application(app_idx=1, state=[to_key_value(b"abc", 123)])
        )
        # this is the app to call which will look for state in the other app
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        # calls the last app
        .with_txn_call().build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


def test_context_txn_accesses_multiple_txns(algod_client: AlgodClient):
    logic = tl.Cond(
        [tl.Txn.on_completion() == tl.OnComplete.OptIn, tl.Return(tl.Int(1))],
        [
            tl.Txn.on_completion() == tl.OnComplete.NoOp,
            tl.Return(tl.Gtxn[0].on_completion() == tl.OnComplete.OptIn),
        ],
    )
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_account(dryruns.Account(utils.idx_to_address(1)))
        # this will opt-in the last account
        .with_txn_call(dryruns.OnComplete.OptInOC)
        # this will do a generic no op call
        .with_txn_call()
        .build_request()
    )
    dryruns.check_err(result)
    # both transactions pass
    assert dryruns.get_messages(result, 0) == ["ApprovalProgram", "PASS"]
    assert dryruns.get_messages(result, 1) == ["ApprovalProgram", "PASS"]


def test_context_txn_accesses_last_timestamp(algod_client: AlgodClient):
    logic = tl.Return(tl.Global.latest_timestamp() == tl.Int(123))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_latest_timestamp(123)
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_txn_call()
        .build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


def test_context_txn_accesses_round(algod_client: AlgodClient):
    logic = tl.Return(tl.Global.round() == tl.Int(123))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_round(123)
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_txn_call()
        .build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


def test_context_txn_accesses_account(algod_client: AlgodClient):
    logic = tl.Return(tl.App.localGet(tl.Txn.sender(), tl.Bytes("abc")) == tl.Int(123))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        # automatically opts into last app
        .with_account_opted_in(local_state=[to_key_value(b"abc", 123)])
        # automatically sets sender to last account
        .with_txn_call()
        .build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


def test_context_txn_accesses_multiple_accounts(algod_client: AlgodClient):
    sender_address = idx_to_address(1)
    state_address = idx_to_address(2)
    logic = tl.Return(
        tl.And(
            # an additional account must be supplied with this local state
            tl.App.localGet(tl.Txn.accounts[1], tl.Bytes("abc")) == tl.Int(123),
            # it must differ from the sender
            tl.Txn.sender() != tl.Addr(state_address),
        )
    )
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_account_opted_in(
            local_state=[to_key_value(b"abc", 123)], address=state_address
        )
        .with_txn_call(sender=sender_address)
        .build_request()
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result) == ["ApprovalProgram", "PASS"]


def test_get_trace_returns_trace(algod_client: AlgodClient):
    logic = tl.Return(tl.Int(1))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_txn_call()
        .build_request()
    )
    assert dryruns.get_trace(result)[-1].source == "return"
    assert dryruns.get_trace(result)[-1].stack == [1]


def test_get_global_deltas_returns_deltas(algod_client: AlgodClient):
    logic = tl.Seq(tl.App.globalPut(tl.Bytes("abc"), tl.Int(123)), tl.Return(tl.Int(1)))
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_txn_call()
        .build_request()
    )
    assert dryruns.get_global_deltas(result) == [dryruns.KeyDelta(b"abc", 123)]


def test_get_global_deltas_returns_deltas(algod_client: AlgodClient):
    logic = tl.Seq(
        tl.App.localPut(tl.Txn.sender(), tl.Bytes("abc"), tl.Int(123)),
        tl.Return(tl.Int(1)),
    )
    result = algod_client.dryrun(
        dryruns.AppCallCtx()
        .with_app_program(apps.compile_source(algod_client, apps.compile_expr(logic)))
        .with_account_opted_in()
        .with_txn_call()
        .build_request()
    )
    assert dryruns.get_local_deltas(result) == {
        idx_to_address(1): [dryruns.KeyDelta(b"abc", 123)]
    }
