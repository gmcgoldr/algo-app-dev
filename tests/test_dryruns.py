import algosdk as ag
import pyteal as tl
from algosdk.future.transaction import ApplicationNoOpTxn
from algosdk.v2client.algod import AlgodClient

from algoappdev import apps, dryruns
from algoappdev.utils import AccountMeta, to_key_value


def test_txn_source_run_executes(
    algod_client: AlgodClient, funded_account: AccountMeta
):
    app_idx = 2 ** 64 - 1
    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_idx
    )
    result = algod_client.dryrun(
        dryruns.source_run(
            stxn=txn.sign(funded_account.key),
            source=apps.compile_expr(tl.Return(tl.Int(1))),
        )
    )
    dryruns.check_err(result)
    assert dryruns.get_trace(result)[-1] == dryruns.TraceItem(
        source="return", stack=[1]
    )


def test_txn_builder_run_creates_app(
    algod_client: AlgodClient, funded_account: AccountMeta
):
    app_builder = apps.AppBuilder()
    txn = app_builder.create_txn(
        algod_client, funded_account.address, algod_client.suggested_params()
    )
    result = algod_client.dryrun(
        dryruns.builder_run(
            stxn=txn.sign(funded_account.key),
            app_builder=app_builder,
        )
    )
    dryruns.check_err(result)
    assert dryruns.get_messages(result)[:2] == ["ApprovalProgram", "PASS"]


def test_txn_buider_run_passes_global_state(
    algod_client: AlgodClient, funded_account: AccountMeta
):
    gstate = apps.StateGlobal([apps.State.KeyInfo(b"a", int, 0)])
    app_builder = apps.AppBuilder(
        on_no_op=tl.Return(gstate.get(b"a") == tl.Int(123)), global_state=gstate
    )
    app_idx = 2 ** 64 - 1

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_idx
    )
    result = algod_client.dryrun(
        dryruns.builder_run(
            stxn=txn.sign(funded_account.key),
            app_builder=app_builder,
            global_state_values=[to_key_value(b"a", 123)],
        )
    )
    dryruns.check_err(result)
    # ensure the global value was retrieved
    assert dryruns.TraceItem("app_global_get", [123]) in dryruns.get_trace(result)
    assert dryruns.get_messages(result)[:2] == ["ApprovalProgram", "PASS"]


def test_txn_buider_run_passes_local_state(
    algod_client: AlgodClient, funded_account: AccountMeta
):
    lstate = apps.StateLocal([apps.State.KeyInfo(b"b", int, 0)])
    app_builder = apps.AppBuilder(
        on_no_op=tl.Return(lstate.get(b"b") == tl.Int(234)),
        local_state=lstate,
    )
    app_idx = 2 ** 64 - 1

    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_idx
    )
    result = algod_client.dryrun(
        dryruns.builder_run(
            stxn=txn.sign(funded_account.key),
            app_builder=app_builder,
            sender_state=dryruns.build_account(
                address=funded_account.address,
                applications=[
                    dryruns.build_application(app_idx, [to_key_value(b"b", 234)])
                ],
            ),
        )
    )
    dryruns.check_err(result)
    # ensure the comparison was carried out
    assert dryruns.TraceItem("app_local_get", [234]) in dryruns.get_trace(result)
    assert dryruns.get_messages(result)[:2] == ["ApprovalProgram", "PASS"]


def test_dryrun_gets_deltas(algod_client: AlgodClient, funded_account: AccountMeta):
    app_idx = 2 ** 64 - 1
    gstate = apps.StateGlobal(
        [
            apps.State.KeyInfo(b"ga", tl.Int, None),
            apps.State.KeyInfo(b"gb", tl.Bytes, None),
        ]
    )
    lstate = apps.StateLocal(
        [
            apps.State.KeyInfo(b"la", tl.Int, None),
            apps.State.KeyInfo(b"lb", tl.Bytes, None),
        ]
    )
    app_builder = apps.AppBuilder(
        on_no_op=tl.Seq(
            gstate.set(b"ga", tl.Int(2)),
            gstate.set(b"gb", tl.Bytes("ab")),
            lstate.set(b"la", tl.Int(20)),
            lstate.set(b"lb", tl.Bytes("abc")),
            tl.Return(tl.Int(1)),
        ),
        global_state=gstate,
        local_state=lstate,
    )
    txn = ApplicationNoOpTxn(
        funded_account.address, algod_client.suggested_params(), app_idx
    )
    result = algod_client.dryrun(
        dryruns.builder_run(
            stxn=txn.sign(funded_account.key),
            app_builder=app_builder,
            global_state_values=[to_key_value(b"ga", 1)],
            sender_state=dryruns.build_account(
                address=funded_account.address,
                applications=[
                    dryruns.build_application(app_idx, [to_key_value(b"lb", b"a")]),
                ],
            ),
        )
    )
    dryruns.check_err(result)

    global_deltas = dryruns.get_global_deltas(result)
    assert set(global_deltas) == {
        dryruns.KeyDelta(b"ga", 2),
        dryruns.KeyDelta(b"gb", b"ab"),
    }

    local_deltas = dryruns.get_local_deltas(result)
    local_deltas = local_deltas[funded_account.address]
    assert set(local_deltas) == {
        dryruns.KeyDelta(b"la", 20),
        dryruns.KeyDelta(b"lb", b"abc"),
    }


def test_txn_context_run_passes_states(
    algod_client: AlgodClient, funded_account: AccountMeta
):
    account_1 = AccountMeta(*ag.account.generate_account())

    app_idx_1 = 2 ** 64 - 1
    gstate_1 = apps.StateGlobal([apps.State.KeyInfo(b"a", int, 0)])
    lstate_1 = apps.StateLocal([apps.State.KeyInfo(b"b", int, 0)])
    gstate_1_ex = apps.StateGlobalExternal(
        [apps.State.KeyInfo(b"a", int, None)], tl.Int(app_idx_1)
    )
    lstate_1_ex = apps.StateLocalExternal(
        [apps.State.KeyInfo(b"b", int, None)],
        tl.Int(app_idx_1),
        tl.Addr(account_1.address),
    )
    app_builder_1 = apps.AppBuilder(
        on_no_op=tl.Return(tl.Int(1)),
        global_state=gstate_1,
        local_state=lstate_1,
    )

    app_idx_2 = 2 ** 64 - 2
    gstate_2 = apps.StateGlobal([apps.State.KeyInfo(b"c", int, 0)])
    lstate_2 = apps.StateLocal([apps.State.KeyInfo(b"d", int, 0)])
    app_builder_2 = apps.AppBuilder(
        on_no_op=tl.Return(
            tl.And(
                # TODO: not working, get ex cannot find the other app
                # gstate_1_ex.load_ex_value(b"a") == tl.Int(123),
                # lstate_1_ex.load_ex_value(b"b") == tl.Int(234),
                gstate_2.get(b"c") == tl.Int(345),
                lstate_2.get(b"d") == tl.Int(456),
                tl.Txn.application_args[0] == tl.Bytes("e"),
            )
        ),
        global_state=gstate_2,
        local_state=lstate_2,
    )

    context = dryruns.AppCallContext(
        stxns=[
            ApplicationNoOpTxn(
                funded_account.address,
                algod_client.suggested_params(),
                app_idx_2,
                app_args=["e"],
                accounts=[account_1.address],
                foreign_apps=[app_idx_1],
            ).sign(funded_account.key)
        ],
        apps=[
            dryruns.build_application_compiled(
                app_idx_1, app_builder_1, algod_client, [to_key_value(b"a", 123)]
            ),
            dryruns.build_application_compiled(
                app_idx_2, app_builder_2, algod_client, [to_key_value(b"c", 345)]
            ),
        ],
        accounts=[
            dryruns.build_account(
                address=account_1.address,
                applications=[
                    dryruns.build_application(app_idx_1, [to_key_value(b"b", 234)])
                ],
            ),
            dryruns.build_account(
                address=funded_account.address,
                applications=[
                    dryruns.build_application(app_idx_2, [to_key_value(b"d", 456)])
                ],
            ),
        ],
    )

    result = algod_client.dryrun(dryruns.context_run(context))

    dryruns.check_err(result)
    assert dryruns.get_messages(result)[:2] == ["ApprovalProgram", "PASS"]
