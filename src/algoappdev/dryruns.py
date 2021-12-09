import base64
import copy
from collections import defaultdict
from typing import Dict, List, NamedTuple, Union

import algosdk as ag
from algosdk.future.transaction import (
    ApplicationCallTxn,
    OnComplete,
    SignedTransaction,
    SuggestedParams,
    Transaction,
)
from algosdk.v2client.models.account import Account
from algosdk.v2client.models.application import Application
from algosdk.v2client.models.application_local_state import ApplicationLocalState
from algosdk.v2client.models.application_params import ApplicationParams
from algosdk.v2client.models.application_state_schema import ApplicationStateSchema
from algosdk.v2client.models.asset import Asset
from algosdk.v2client.models.asset_holding import AssetHolding
from algosdk.v2client.models.dryrun_request import DryrunRequest
from algosdk.v2client.models.teal_key_value import TealKeyValue

from algoappdev.utils import (
    ZERO_ADDRESS,
    AlgoAppDevError,
    address_to_idx,
    from_value,
    idx_to_address,
)

MAX_SCHEMA = ApplicationStateSchema(64, 64)


class TraceItem(NamedTuple):
    source: str
    stack: List[Union[int, bytes]]
    program_counter: int

    def __str__(self) -> str:
        # max 12 char stack value
        stack = [str(v) for v in self.stack]
        stack = [(v[:7] + ".." + v[-3:] if len(v) > 12 else v) for v in stack]
        stack = [f"{v:12s}" for v in stack]
        stack = ", ".join(stack)
        # max 40 char source code
        source = self.source
        if len(source) > 40:
            source = source[:-37] + "..."
        return f"{self.program_counter:5d} :: {source:40s} :: [{stack}]"


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
    app_idx: int,
    approval_program: bytes = None,
    clear_state_program: bytes = None,
    global_schema: ApplicationStateSchema = None,
    local_schema: ApplicationStateSchema = None,
    state: List[TealKeyValue] = None,
    creator: str = None,
) -> Application:
    """
    Build an Application with a given `app_idx`.

    With just the `app_idx` specified, the app cannot be used in a transaction.

    The programs can be set to allow the app logic to be called. Note that the
    `approval_program` is the one called for all `on_complete` code other than
    the `ClearState` code. Those transcations will call `clear_state_program`.

    If the schemas are `None`, default to the most permissive schema (64 byte
    slices and 64 ints).

    Use `state` to provide key-value pairs for the app's global state.
    """
    global_schema = global_schema if global_schema is not None else MAX_SCHEMA
    local_schema = local_schema if local_schema is not None else MAX_SCHEMA
    return Application(
        id=app_idx,
        params=ApplicationParams(
            creator=creator,
            global_state=state,
            approval_program=approval_program,
            clear_state_program=clear_state_program,
            global_state_schema=global_schema,
            local_state_schema=local_schema,
        ),
    )


def build_account(
    address: str,
    local_states: List[ApplicationLocalState] = None,
    assets: List[AssetHolding] = None,
    microalgos: int = None,
    status: str = "Offline",
) -> Account:
    """
    Build an account with the given `address`.

    With just the `address` specified, the account cannot be used in a
    transaction.

    Use `local_states` to provide key-value pairs for various apps this account
    has opted into. The actual state can be empty to indicate the account has
    opted in, but has nothing set in its local storage.

    Use `assets` to provide information about assets owned by the account.

    Use `mircoalgos` to provide a balance of Algo owned by the account.
    """
    return Account(
        address=address,
        amount=microalgos,
        apps_local_state=local_states,
        assets=assets,
        status=status,
    )


class AppCallCtx:
    """
    Describes the context (arguments) seen by an app when called by a group
    of transactions.
    """

    def __init__(self):
        # applications with state and / or logic accessed by transactions
        self.apps: List[Application] = []
        # transactions, at least one of which should call an app
        self.txns: List[Transaction] = []
        # accounts state accessed by the apps
        self.accounts: List[Account] = []
        # assets accessed by the apps
        self.assets: List[Asset] = []
        # last timestamp on the ledger
        self.latest_timestamp: int = None
        # last round number on the ledger
        self.round: int = None

    def _next_app_idx(self) -> int:
        if not self.apps:
            return 1
        app_idxs = {a.id for a in self.apps}
        for idx in sorted(app_idxs):
            if idx < 2 ** 64 - 1 and idx + 1 not in app_idxs:
                return idx + 1
        # system will be out of memory before this happens
        return None

    def _next_account_address(self) -> str:
        if not self.accounts:
            return idx_to_address(1)
        account_idxs = {address_to_idx(a.address) for a in self.accounts}
        for idx in sorted(account_idxs):
            if idx < 2 ** 64 - 1 and idx + 1 not in account_idxs:
                return idx_to_address(idx + 1)
        # system will be out of memory before this happens
        return None

    def _last_app_idx(self) -> int:
        return self.apps[-1].id if self.apps else 0

    def _last_account_address(self) -> str:
        return self.accounts[-1].address if self.accounts else ZERO_ADDRESS

    def suggested_params(self) -> SuggestedParams:
        """
        Build minimal transaction parameters which will work with dry run.

        Defaults to using the minimal network fee, and allowing the maximum
        transaction lifetime for execution, from the current `round` or from
        the first round.
        """
        first = self.round if self.round is not None else 1
        return SuggestedParams(
            fee=ag.constants.min_txn_fee,
            first=first,
            # currently this is the network's maximum transaction life, but this
            # could change and isn't part of the SDK
            last=first + 1000 - 1,
            gh="",
            flat_fee=True,
        )

    def with_latest_timestamp(self, latest_timestamp: int) -> "AppCallCtx":
        """Set the latest timestamp (`Global.latest_timestamp`)"""
        ctx = copy.deepcopy(self)
        ctx.latest_timestamp = latest_timestamp
        return ctx

    def with_round(self, round: int) -> "AppCallCtx":
        """Set the last round (`Global.round`)"""
        ctx = copy.deepcopy(self)
        ctx.round = round
        return ctx

    def with_app(self, app: Application) -> "AppCallCtx":
        """
        Add an application. If this application is being called, its source
        program(s) must be supplied.
        """
        ctx = copy.deepcopy(self)
        ctx.apps.append(copy.deepcopy(app))
        return ctx

    def with_app_program(
        self,
        program: bytes = None,
        app_idx: int = None,
        state: List[TealKeyValue] = None,
    ) -> "AppCallCtx":
        """
        Add an application with defaults and possibly an approval program.

        If `app_idx` is omitted, defaults to the next available app idx not in
        the `apps`.
        """
        app_idx = app_idx if app_idx is not None else self._next_app_idx()
        return self.with_app(
            build_application(app_idx=app_idx, approval_program=program, state=state)
        )

    def with_account(self, account: Account) -> "AppCallCtx":
        """Add an account with some local state."""
        ctx = copy.deepcopy(self)
        ctx.accounts.append(copy.deepcopy(account))
        return ctx

    def with_account_opted_in(
        self,
        app_idx: int = None,
        address: str = None,
        local_state: List[TealKeyValue] = None,
    ) -> "AppCallCtx":
        """
        Add an account which is opted into to an app.

        If `app_idx` is omitted, defaults to the index of the last added app.

        If `address` is omitted, defaults to the next available address not in
        the `accounts`.

        If `local_state` isn't provided, then the account is seen to be opted
        into the app, but with no local storage set.
        """
        address = address if address is not None else self._next_account_address()
        app_idx = app_idx if app_idx is not None else self._last_app_idx()
        account = build_account(
            address,
            local_states=[ApplicationLocalState(id=app_idx, key_value=local_state)],
        )
        return self.with_account(account)

    def with_txn(self, txn: Transaction) -> "AppCallCtx":
        """
        Add a transaction.

        NOTE: for an `ApplicationCreateTxn`, the transaction sender must match
        the application creator. The zero address can be used for both.
        """
        ctx = copy.deepcopy(self)
        ctx.txns.append(copy.deepcopy(txn))
        return ctx

    def with_txn_call(
        self,
        on_complete: OnComplete = OnComplete.NoOpOC,
        sender: str = None,
        params: SuggestedParams = None,
        app_idx: int = None,
        args: List[bytes] = None,
    ) -> "AppCallCtx":
        """
        Add a transaction which calls an app.

        If `sender` is omitted, defaults to the address of the last added
        account.

        If `params` is omitted, defaults to the result of `suggested_params`.

        If `app_idx` is omitted, defaults to the index of the last added app.
        """
        app_idx = app_idx if app_idx is not None else self._last_app_idx()
        return self.with_txn(
            ApplicationCallTxn(
                sender=sender if sender is not None else self._last_account_address(),
                sp=params if params is not None else self.suggested_params(),
                index=app_idx,
                on_complete=on_complete,
                app_args=args,
                accounts=[a.address for a in self.accounts],
                foreign_apps=[a.id for a in self.apps],
                foreign_assets=[a.index for a in self.assets],
            )
        )

    def build_request(self) -> DryrunRequest:
        """Build the dry run request."""
        # dryrun expects signed transactions but doesn't actually use the
        # signature data, so set it to None
        signed_txns = [
            SignedTransaction(t, None) if not isinstance(t, SignedTransaction) else t
            for t in self.txns
        ]
        return DryrunRequest(
            txns=signed_txns,
            apps=self.apps,
            accounts=self.accounts,
            # not clear if this is accessed anywhere
            protocol_version=None,
            round=self.round,
            latest_timestamp=self.latest_timestamp,
            # sources are already compiled and included in the apps
            sources=None,
        )


def check_err(result: Dict):
    """Raise an error if the result contains an execution error."""
    message = result.get("error", None)
    if message:
        raise AlgoAppDevError(f"dryrun error: {message}")


def get_messages(result: Dict, txn_idx: int = 0) -> List[str]:
    """Get the list of execution messages for transaction `txn_idx`."""
    try:
        txn = result.get("txns", [])[txn_idx]
    except IndexError:
        return []
    return txn.get("app-call-messages", [])


def get_trace(result: Dict, txn_idx: int = 0) -> List[TraceItem]:
    """Get the list of trace lines for transaction `txn_idx`."""
    try:
        txn = result.get("txns", [])[txn_idx]
    except IndexError:
        return []

    trace_items = []

    lines = txn.get("disassembly", None)
    trace = txn.get("app-call-trace", None)
    if lines is None or trace is None:
        return []

    for item in trace:
        line = lines[item["line"] - 1]
        stack = [from_value(i) for i in item["stack"]]
        trace_items.append(TraceItem(line, stack, item["pc"]))

    return trace_items


def get_global_deltas(result: Dict, txn_idx: int = 0) -> List[KeyDelta]:
    """Get the list of global key deltas for transaction `txn_idx`."""
    try:
        txn = result.get("txns", [])[txn_idx]
    except IndexError:
        return []
    return [KeyDelta.from_result(d) for d in txn.get("global-delta")]


def get_local_deltas(result: Dict, txn_idx: int = 0) -> Dict[str, List[KeyDelta]]:
    """Get the list of local key deltas for transaction `txn_idx`."""
    try:
        txn = result.get("txns", [])[txn_idx]
    except IndexError:
        return []

    local_deltas = defaultdict(list)
    for local_delta in txn.get("local-deltas", []):
        address = local_delta["address"]
        deltas = local_delta["delta"]
        if address is None or deltas is None:
            continue
        local_deltas[address] += [KeyDelta.from_result(d) for d in deltas]

    return dict(local_deltas)
