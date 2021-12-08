import base64
from collections import defaultdict
from typing import Dict, List, NamedTuple, Union

from algosdk.future.transaction import (
    ApplicationCallTxn,
    OnComplete,
    SignedTransaction,
    StateSchema,
)
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.models.account import Account
from algosdk.v2client.models.application import Application
from algosdk.v2client.models.application_local_state import ApplicationLocalState
from algosdk.v2client.models.application_params import ApplicationParams
from algosdk.v2client.models.application_state_schema import ApplicationStateSchema
from algosdk.v2client.models.dryrun_request import DryrunRequest
from algosdk.v2client.models.dryrun_source import DryrunSource
from algosdk.v2client.models.teal_key_value import TealKeyValue

from algoappdev import apps
from algoappdev.apps import AppBuilder, compile_expr
from algoappdev.utils import AlgoAppDevError, from_value


class AppCallContext(NamedTuple):
    stxns: List[SignedTransaction]
    apps: List[Application]
    accounts: List[Account]
    latest_timestamp: int = None
    round: int = None


class TraceItem(NamedTuple):
    source: str
    stack: List[Union[int, bytes]]

    def __str__(self) -> str:
        stack = ", ".join(map(str, self.stack))
        return f"{self.source} → [{stack}]"


class KeyDelta(NamedTuple):
    key: bytes
    value: int

    @staticmethod
    def from_result(result: Dict) -> "KeyDelta":
        key = base64.b64decode(result["key"])
        value = result["value"].get("uint", None)
        if value is None:
            value = result["value"].get("bytes", None)
            value = base64.b64decode(value)
        return KeyDelta(key, value)


def build_application(
    app_idx: int, state: List[TealKeyValue] = None, creator: str = None
) -> Application:
    """
    Build an `Application` information object which can be used to pass global
    state to a dry run.

    NOTE: this `Application` object doesn't carry its source code, so it
    must be used with `DryrunSource` if it is called. Typically, this would
    instead be used just to pass external application state.

    Args:
        app_idx: the application index, can be zero to simulation app creation
        state: the global state
        creator: the creator's address

    Returns:
        the `Application` information object
    """
    return Application(
        id=app_idx,
        params=ApplicationParams(
            creator=creator,
            global_state=state,
        ),
    )


def _schema_to_model(schema: StateSchema) -> ApplicationStateSchema:
    return ApplicationStateSchema(
        num_byte_slice=schema.num_byte_slices,
        num_uint=schema.num_uints,
    )


def build_application_compiled(
    app_idx: int,
    builder: AppBuilder,
    client: AlgodClient,
    state: List[TealKeyValue] = None,
    creator: str = None,
) -> Application:
    """
    Build an `Application` information object and compile the programs into the
    object so that it can be used in a dry run.

    Args:
        app_idx: the application index, can be zero to simulation app creation
        state: the global state
        creator: the creator's address

    Returns:
        the `Application` information object
    """
    return Application(
        id=app_idx,
        params=ApplicationParams(
            creator=creator,
            global_state=state,
            local_state_schema=_schema_to_model(builder.local_schema()),
            global_state_schema=_schema_to_model(builder.global_schema()),
            approval_program=apps.compile_source(
                client, apps.compile_expr(builder.approval_expr())
            ),
            clear_state_program=apps.compile_source(
                client, apps.compile_expr(builder.clear_exrp())
            ),
        ),
    )


def build_account(
    address: str,
    applications: List[Application] = [],
    microalgos: int = None,
) -> Account:
    return Account(
        address=address,
        amount=microalgos,
        apps_local_state=[
            ApplicationLocalState(id=a.id, key_value=a.params.global_state)
            for a in applications
        ],
        status="Offline",
    )


def source_run(
    stxn: SignedTransaction,
    source: str,
    global_state_values: List[TealKeyValue] = [],
    sender_state: Account = None,
) -> DryrunRequest:
    """
    Build a `DryrunRequest` from a transaction and some TEAL source.

    This is the simplest dryrun harness, allowing for quickly debugging a
    standalone TEAL program.

    NOTE: if the transaciton application index is not specified, it defaults
    to the largest value `2**64 - 1`. So this value should be used to refer to
    the app being built. If the `sender_state` includes an `AppState` with no
    `app_idx` (zero or None), then it will be set to the current app index.

    Args:
        stxn: the signed transaction used to call the app
        source: the teal source code to run
        global_state_values: the app's global state
        sender_state: the sender's state

    Returns:
        the dryrun request object
    """
    txn: ApplicationCallTxn = stxn.transaction
    try:
        OnComplete(txn.on_complete)
    except (AttributeError, ValueError):
        raise AlgoAppDevError("transaction must be an application call")

    app_idx = txn.index
    if app_idx == 0:
        app_idx = 2 ** 64 - 1

    app = Application(
        id=app_idx,
        params=ApplicationParams(
            creator=txn.sender,
            # use a generic state schema allowing for the maximal storage
            local_state_schema=ApplicationStateSchema(64, 64),
            global_state_schema=ApplicationStateSchema(64, 64),
            global_state=global_state_values,
        ),
    )

    account = (
        build_account(address=txn.sender) if sender_state is None else sender_state
    )

    source = DryrunSource(
        # run as the approval program as this is a standalone run so the clear
        # program semantics aren't too useful
        field_name="approv",
        source=source,
        app_index=app_idx,
    )

    return DryrunRequest(
        txns=[stxn],
        apps=[app],
        accounts=[account],
        sources=[source],
    )


def builder_run(
    stxn: SignedTransaction,
    app_builder: AppBuilder,
    global_state_values: List[TealKeyValue] = [],
    sender_state: Account = None,
) -> DryrunRequest:
    """
    Build a `DryrunRequest` from a transaction and an `ApplicationBuilder`.

    An `Application` is built using the `app_builder` teal expressions, and
    schemas. If the call needs global state, it can be passed in the
    `global_state_values` list.

    See: `expression_run`.

    Args:
        stxn: the signed transaction used to call the app
        app_builder: the app builder specifying the teal expressions and schema
        global_state_values: the app's global state
        sender_state: the sender's state

    Returns:
        the dryrun request object
    """
    txn: ApplicationCallTxn = stxn.transaction
    try:
        on_complete = OnComplete(txn.on_complete)
    except (AttributeError, ValueError):
        raise AlgoAppDevError("transaction must be an application call")

    app_idx = txn.index
    if app_idx == 0:
        app_idx = 2 ** 64 - 1

    app = Application(
        id=app_idx,
        params=ApplicationParams(
            creator=txn.sender,
            local_state_schema=_schema_to_model(app_builder.local_schema()),
            global_state_schema=_schema_to_model(app_builder.global_schema()),
            global_state=global_state_values,
        ),
    )

    account = (
        build_account(address=txn.sender) if sender_state is None else sender_state
    )

    is_clear = on_complete is OnComplete.ClearStateOC
    field_name = "clearp" if is_clear else "approv"
    source = DryrunSource(
        field_name=field_name,
        source=compile_expr(
            app_builder.clear_exrp() if is_clear else app_builder.approval_expr()
        ),
        app_index=app_idx,
    )

    return DryrunRequest(
        txns=[stxn],
        apps=[app],
        accounts=[account],
        sources=[source],
    )


def context_run(context: AppCallContext) -> DryrunRequest:
    """
    Build a `DryrunRequest` from a full `AppCallContext`.

    TODO: this doesn't yet work with multiple applications, and hasn't been
    tested for transaction groups.

    Args:
        context: call context

    Returns:
        the dryrun request object
    """
    return DryrunRequest(
        txns=context.stxns,
        apps=context.apps,
        accounts=context.accounts,
        sources=None,
        latest_timestamp=context.latest_timestamp,
        round=context.round,
    )


def check_err(result: Dict):
    message = result.get("error", None)
    if message:
        raise AlgoAppDevError(f"dryrun error: {message}")


def get_messages(result: Dict) -> List[str]:
    return [m for t in result.get("txns", []) for m in t.get("app-call-messages", [])]


def get_trace(result: Dict) -> List[TraceItem]:
    for txn in result.get("txns", []):
        lines = txn.get("disassembly", None)
        trace = txn.get("app-call-trace", None)
        if lines is None or trace is None:
            continue
        break
    else:
        return []

    trace_items = []
    for item in trace:
        line = lines[item["line"] - 1]
        stack = [from_value(i) for i in item["stack"]]
        trace_items.append(TraceItem(line, stack))

    return trace_items


def get_global_deltas(result: Dict) -> List[KeyDelta]:
    deltas = []
    for txn in result.get("txns", []):
        deltas += txn.get("global-delta", [])
    return [KeyDelta.from_result(d) for d in deltas]


def get_local_deltas(result: Dict) -> Dict[str, List[KeyDelta]]:
    local_deltas = defaultdict(list)
    for txn in result.get("txns", []):
        for local_delta in txn.get("local-deltas", []):
            address = local_delta["address"]
            deltas = local_delta["delta"]
            if address is None or deltas is None:
                continue
            local_deltas[address] += [KeyDelta.from_result(d) for d in deltas]
    return dict(local_deltas)
