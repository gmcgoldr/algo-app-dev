"""Utilities for building and transacting with apps."""

import base64
from typing import Dict, List, NamedTuple, Type, Union

import pyteal as tl
from algosdk.future.transaction import (
    ApplicationCreateTxn,
    ApplicationUpdateTxn,
    OnComplete,
    StateSchema,
    SuggestedParams,
)
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.models.application import Application
from algosdk.v2client.models.application_params import ApplicationParams
from algosdk.v2client.models.application_state_schema import ApplicationStateSchema
from algosdk.v2client.models.teal_key_value import TealKeyValue

from .utils import AlgoAppDevError

Key = Union[int, str, bytes]
TealType = Union[Type[tl.Int], Type[tl.Bytes]]
TealValue = Union[tl.Int, tl.Bytes]

ZERO = tl.Int(0)
ONE = tl.Int(1)


def compile_expr(expr: tl.Expr) -> str:
    """
    Compile a teal expression to teal source code:

    Args:
        expr: the teal expression

    Returns:
        the teal source code
    """
    return tl.compileTeal(
        expr,
        mode=tl.Mode.Application,
        version=tl.MAX_TEAL_VERSION,
    )


def compile_source(client: AlgodClient, source: str) -> bytes:
    """
    Compile teal source code into bytes.

    Args:
        client: the client connected to a node with the developer API
        source: the teal source code

    Returns:
        the teal program bytes
    """
    result = client.compile(source)
    result = result["result"]
    return base64.b64decode(result)


class State:
    """Describes an app's state."""

    class KeyInfo:
        """
        Information about an app state key and associated value.
        """

        def __init__(self, key: Key, type: TealType, default: tl.Expr = None):
            """
            Args:
                key: the key used to retreive this some state
                type: the PyTeal type `tl.Int` or `tl.Bytes`
                default: a PyTeal expression which produces a default value
            """
            key = self.as_bytes(key)
            # the key as bytes
            self.key = key
            # the tl type of the key's value
            self.type = type
            # the tl expression to populate the initial value (can be None)
            self.default = default

        @staticmethod
        def as_bytes(key: Key) -> bytes:
            """
            Convert a key to it's byte representation. Validates that the key
            length doesn't surpass the Algorand maximum of 64 bytes.
            """
            if isinstance(key, int):
                # At most 64 keys are allowed, so this fits in a byte. The
                # byte order is arbitrary as this is handled internally, but
                # use big-endian anyway to be consistent with TEAL conventions.
                key = key.to_bytes(1, "big")
            if isinstance(key, str):
                return key.encode("utf8")
            elif isinstance(key, bytes):
                pass
            else:
                raise AlgoAppDevError(f"invalid key type: {type(key)}")
            if len(key) > 64:
                raise AlgoAppDevError(f"key too long: {key}")
            return key

    def __init__(self, keys: List[KeyInfo]):
        """
        Args:
            keys: list of key information describing the state
        """
        self._key_to_info = {i.key: i for i in keys}
        self._maybe_values: Dict[bytes, tl.MaybeValue] = {}

    def key_info(self, key: Key):
        """Get the `KeyInfo` for `key`."""
        return self._key_to_info[State.KeyInfo.as_bytes(key)]

    def key_infos(self) -> List[KeyInfo]:
        """Get the list of `KeyInfo`s for the entire state."""
        return list(self._key_to_info.values())

    def schema(self) -> StateSchema:
        """Build the schema for the state."""
        num_uints = 0
        num_byte_slices = 0

        for info in self._key_to_info.values():
            if info.type is tl.Int:
                num_uints += 1
            elif info.type is tl.Bytes:
                num_byte_slices += 1

        return StateSchema(num_uints=num_uints, num_byte_slices=num_byte_slices)


class StateGlobalExternal(State):
    """
    Read global state values which might or might not be present. This is the
    only way to interface with external apps, and can also be used to access
    values which might not yet be set in the current app.

    An object `MaybeValue` is itself a teal expression. It is also stateful,
    in that the expression, once constructed, stores the value into a slot,
    and that slot is cached in the `MaybeValue` object.

    For example:

    ```
    myabe = App.globalGetEx(app_id, key)
    Seq(maybe, maybe.value())
    ```

    In this snippet, the sequence first stores the values retrieved by get,
    then the value is loaded onto the stack and can be used. To re-use the
    value from the given `key`, it is necessary to use the *same* `maybe`
    objet, as this one remembers which slot the value is stored in.

    Making a second `MaybeValue` object with the same key will not re-use the
    stored values from the first object. The second object could also evaluated
    to store the same value into a *new* slot. But without this step, it's
    `load` method is oblivious to the slots used by the `globalGetEx` call.
    """

    def __init__(self, keys: List[State.KeyInfo], app_id: tl.Expr):
        """
        See `State.__init__`.

        Args:
            app_id: expression evaluating to the id of an app in the app array
        """
        super().__init__(keys)
        self.app_id = app_id

    def get_ex(self, key: Key) -> tl.MaybeValue:
        """
        Get the `MaybeValue` object for `key`.

        The object itself is an expression to load the value into a slot. It
        also has members for accessing that value.

        After evaluating `MaybeValue`, then that object can be used to generate
        expression to access the value: `MaybeValue.value`. This means that a
        `MaybeValue` object must be cached if its value is to be accessed more
        than once, so it can remember which slot the value was stored in.
        """
        info = self.key_info(key)
        maybe_value = self._maybe_values.get(info.key, None)
        if maybe_value is None:
            maybe_value = tl.App.globalGetEx(self.app_id, tl.Bytes(info.key))
            self._maybe_values[info.key] = maybe_value
        return maybe_value

    def load_ex_value(self, key: Key) -> tl.Expr:
        """
        Load a `MaybeValue` into a slot and return its value.

        If the key was previously loaded, the same scratch slot will be used.
        However, this will call `globalGetEx` and store its result anew, albeit
        in the same slot.

        The cost of repeating these operations can be avoided by pre-storing
        the value into a slot at the start of the program, and then accessing
        its `load` member subsequently.

        ```
        maybe = state.get_ex(key)
        expr = Seq(
            maybe,
            # ... some teal logic, with possible branches
            maybe.value()
            # ... some more teal logic
            maybe.value()
        )
        ```
        """
        maybe_value = self.get_ex(key)
        return tl.Seq(maybe_value, maybe_value.value())

    def load_ex_has_value(self, key: Key) -> tl.Expr:
        """
        Load a `MaybeValue` into a slot and return if it has a value.

        See `load_ex_value` for notes on the `globalGetEx` calls.
        """
        maybe_value = self.get_ex(key)
        return tl.Seq(maybe_value, maybe_value.hasValue())


class StateGlobal(StateGlobalExternal):
    def __init__(
        self,
        keys: List[State.KeyInfo],
    ):
        """See `StateGlobalExternal.__init__` but for only the current app."""
        # only state of the current application can be written
        super().__init__(keys, tl.Global.current_application_id())

    def get(self, key: Key) -> tl.Expr:
        """Build the expression to get the state value at `key`"""
        info = self.key_info(key)
        return tl.App.globalGet(tl.Bytes(info.key))

    def set(self, key: Key, value: TealValue) -> tl.Expr:
        """Build the expression to set the state `value` at `key`"""
        info = self.key_info(key)
        return tl.App.globalPut(tl.Bytes(info.key), value)

    def drop(self, key: Key) -> tl.Expr:
        """Build the expression to drop the state `key`"""
        info = self.key_info(key)
        return tl.App.globalDel(tl.Bytes(info.key))

    def constructor(self) -> tl.Expr:
        """
        Build the expression to set the initial state values for those keys
        with an `default` member.
        """
        return tl.Seq(
            *[
                tl.App.globalPut(tl.Bytes(i.key), i.default)
                for i in self.key_infos()
                if i.default
            ]
        )


class StateLocalExternal(State):
    """See `StateGlobalExternal`, but for the local state."""

    def __init__(self, keys: List[State.KeyInfo], app_id: tl.Expr, account: tl.Expr):
        """
        See `State.__init__`.

        Args:
            app_id: expression evaluating to the id of an app in the app array
            account: expression evaluating to the account whose state is to be
                accessed
        """
        super().__init__(keys)
        self.app_id = app_id
        self.account = account

    def get_ex(self, key: Key) -> tl.MaybeValue:
        """
        See `StateGlobalExternal.get_ex`.
        """
        info = self.key_info(key)
        maybe_value = self._maybe_values.get(info.key, None)
        if maybe_value is None:
            maybe_value = tl.App.localGetEx(
                self.account, self.app_id, tl.Bytes(info.key)
            )
            self._maybe_values[info.key] = maybe_value
        return maybe_value

    def load_ex_value(self, key: Key) -> tl.Expr:
        """
        See `StateGlobalExternal.load_ex_value`.
        """
        maybe_value = self.get_ex(key)
        return tl.Seq(maybe_value, maybe_value.value())

    def load_ex_has_value(self, key: Key) -> tl.Expr:
        """
        See `StateGlobalExternal.load_ex_has_value`.
        """
        maybe_value = self.get_ex(key)
        return tl.Seq(maybe_value, maybe_value.hasValue())


class StateLocal(StateLocalExternal):
    def __init__(
        self,
        keys: List[State.KeyInfo],
        account: tl.Expr = None,
    ):
        """
        See `StateLocalExternal.__init__` but for only the current app.

        The account whose local state is accessed can be specified with
        `account`, and defaults to the transaction sender.
        """
        # only state of the current application can be written, but any
        # account which has opted-in can be modified
        super().__init__(
            keys,
            tl.Global.current_application_id(),
            account if account is not None else tl.Txn.sender(),
        )

    def get(self, key: Key) -> tl.Expr:
        """See `StateGlobal.get`."""
        info = self.key_info(key)
        return tl.App.localGet(self.account, tl.Bytes(info.key))

    def set(self, key: Key, value: TealValue) -> tl.Expr:
        """See `StateGlobal.set`."""
        info = self.key_info(key)
        return tl.App.localPut(self.account, tl.Bytes(info.key), value)

    def drop(self, key: Key) -> tl.Expr:
        """See `StateGlobal.drop`."""
        info = self.key_info(key)
        return tl.App.localDel(self.account, tl.Bytes(info.key))

    def constructor(self) -> tl.Expr:
        """See `StateGlobal.constructor`."""
        return tl.Seq(
            *[
                tl.App.localPut(self.account, tl.Bytes(i.key), i.default)
                for i in self.key_infos()
                if i.default
            ]
        )


class AppBuilder(NamedTuple):
    """
    Build the program data required for an app to execute the provided
    expressions, with the provided app state.

    The app is specified as individual branches. At most one of those branches
    will execute when the application is called (all branches are joined in a
    `tl.Seq` expression, which must evaluate exactly one branch).

    Branches that can execute for an `ApplicationCall` transaction:

    - `on_create`: this expression is run when the app is first created only,
      and if it returns zero, the app cannot be created.
    - `on_delete`: this expression is run when a `DeleteApplication`
      transaction is sent, and if it returns zero the app cannot be deleted.
    - `on_update`: this expression is run when a `UpdateApplication`
      transaction is sent, and if it returns zero the app cannot be updated.
    - `on_opt_in`: this expression is run when a `OptIn` transaction is sent,
      and if it returns zero the app cannot be opted-in by accounts.
    - `on_close_out`: this expression is run when a `CloseOut` transaction is
      sent, and if it returns zero the app cannot be closed out by accounts.
    - `invocations[name]`: these expressions are run when a `NoOp` transaction
      is sent, and the first argument passed to the call is the bytes encoding
      of `name`.
    - `on_no_op`: this expression is run when a `NoOp` transaction is sent, and
      no invocation matches the first call argument (if supplied). This is the
      "default invocation".

    Branch that executes for a `ClearState` transaction:

    - `on_clear`: this expression is run regardless of return value, but any
      state changes made in the expression are not committed if the return
      value is zero.

    The default app implements the following functionality:

    - creation is allowed and sets the global state defaults
    - deletion is not allowed
    - updating is not allowed
    - opt in is allowed and sets the local state defaults
    - close out is not allowed
    - clear is allowed
    - no invocations
    - no default invocation
    """

    on_create: tl.Expr = None
    on_delete: tl.Expr = None
    on_update: tl.Expr = None
    on_opt_in: tl.Expr = None
    on_close_out: tl.Expr = None
    on_clear: tl.Expr = None
    invocations: Dict[str, tl.Expr] = None
    on_no_op: tl.Expr = None
    global_state: StateGlobal = None
    local_state: StateLocal = None

    def approval_expr(self) -> tl.Expr:
        """
        Assemble the provided expressions into the approval expression, by
        joining them in a single branching control flow.
        """
        # Each branch is a pair of expressions: one which tests if the branch
        # should be executed, and another which is the branche's logic. If the
        # branch logic returns 0, then the app state is unchanged, no matter what
        # operations were performed during its execution (i.e. it rolls back). Only
        # the first matched branch is executed.
        branches = []

        on_create = self.on_create
        if not on_create:
            if self.global_state is not None:
                on_create = tl.Seq(self.global_state.constructor(), tl.Return(ONE))
            else:
                on_create = tl.Return(ONE)
        branches.append([tl.Txn.application_id() == ZERO, on_create])

        if self.on_delete:
            branches.append(
                [
                    tl.Txn.on_completion() == tl.OnComplete.DeleteApplication,
                    self.on_delete,
                ]
            )

        if self.on_update:
            branches.append(
                [
                    tl.Txn.on_completion() == tl.OnComplete.UpdateApplication,
                    self.on_update,
                ]
            )

        on_opt_in = self.on_opt_in
        if not on_opt_in:
            if self.local_state is not None:
                on_opt_in = tl.Seq(self.local_state.constructor(), tl.Return(ONE))
            else:
                on_opt_in = tl.Return(ONE)
        branches.append([tl.Txn.on_completion() == tl.OnComplete.OptIn, on_opt_in])

        if self.on_close_out:
            branches.append(
                [tl.Txn.on_completion() == tl.OnComplete.CloseOut, self.on_close_out]
            )

        # handle custom invocations with named arg
        invocations = {} if self.invocations is None else self.invocations
        for name, expr in invocations.items():
            branches.append(
                [
                    # use a an invocation branch for no-op calls with the branch
                    # name as arg 0
                    tl.And(
                        tl.Txn.on_completion() == tl.OnComplete.NoOp,
                        tl.If(tl.Txn.application_args.length() >= ONE)
                        # if there is an argument passed, then it must match
                        # the invocation name
                        .Then(tl.Txn.application_args[0] == tl.Bytes(name))
                        # otherwise fail the branch
                        .Else(ZERO),
                    ),
                    expr,
                ]
            )

        # if no invocation matched, then try the default no-op
        if self.on_no_op:
            branches.append(
                [tl.Txn.on_completion() == tl.OnComplete.NoOp, self.on_no_op]
            )

        # fallthrough: if no branch is selected, reject
        branches.append([ONE, tl.Return(ZERO)])

        return tl.Cond(*branches)

    def clear_expr(self) -> tl.Expr:
        """Build the clear program expression."""
        return self.on_clear if self.on_clear is not None else tl.Return(ONE)

    def global_schema(self) -> StateSchema:
        """Build the global schema."""
        return (
            self.global_state.schema()
            if self.global_state is not None
            else StateSchema()
        )

    def local_schema(self) -> StateSchema:
        """Build the local schema."""
        return (
            self.local_state.schema() if self.local_state is not None else StateSchema()
        )

    def create_txn(
        self, client: AlgodClient, address: str, params: SuggestedParams
    ) -> ApplicationCreateTxn:
        """
        Build the transaction which creates the app.

        Args:
            client: the client connected to a node with the developer API, used
                for compiling and to send the transaction
            address: the address of the app creator sending the transaction
            params: the transaction parameters
        """
        # create empty schemas if none are provided
        return ApplicationCreateTxn(
            # this will be the app creator
            sender=address,
            sp=params,
            # no state change requested in this transaciton beyond app creation
            on_complete=OnComplete.NoOpOC.real,
            # the program to handle app state changes
            approval_program=compile_source(client, compile_expr(self.approval_expr())),
            # the program to run when an account forces an opt-out
            clear_program=compile_source(client, compile_expr(self.clear_expr())),
            # the amount of storage used by the app
            global_schema=self.global_schema(),
            local_schema=self.local_schema(),
        )

    def update_txn(
        self,
        client: AlgodClient,
        address: str,
        params: SuggestedParams,
        app_id: int,
    ) -> ApplicationUpdateTxn:
        """
        Build the transaction which updates an app with this data.

        NOTE: the schema cannot be changed in an update transaction, meaning
        the state must be the same as that already used in `app_id`.

        Args:
            client: the client connected to a node with the developer API, used
                for compiling and to send the transaction
            address: the address of the app creator sending the transaction
            params: the transaction parameters
            app_id: the id of the existing application to update
        """
        # ensure a valid clear program, interpret None as return zero
        return ApplicationUpdateTxn(
            sender=address,
            sp=params,
            index=app_id,
            approval_program=compile_source(client, compile_expr(self.approval_expr())),
            clear_program=compile_source(client, compile_expr(self.clear_expr())),
        )

    def build_application(
        self,
        client: AlgodClient,
        app_idx: int,
        creator: str = None,
        global_state: List[TealKeyValue] = None,
    ) -> Application:
        """
        Build the `Application` object describing this application.

        This is used to interface with the dryrun APIs.

        Args:
            client: the client connected to a node with the developer API, used
                for compiling and to send the transaction
            app_idx: the application index to assign to this app, used to cross
                reference in transactions and other apps in the dry run
            creator: the application's creator's address, needed if the logic
                accesses `tl.Global.creator_address`, and for making a dryrun
                of the app creation
            global_state: attach this global state to the app in the dryrun
        """
        global_schema = self.global_schema()
        local_schema = self.local_schema()
        global_state_schema = ApplicationStateSchema(
            num_uint=global_schema.num_uints,
            num_byte_slice=global_schema.num_byte_slices,
        )
        local_state_schema = ApplicationStateSchema(
            num_uint=local_schema.num_uints,
            num_byte_slice=local_schema.num_byte_slices,
        )
        return Application(
            id=app_idx,
            params=ApplicationParams(
                creator=creator,
                approval_program=compile_source(
                    client, compile_expr(self.approval_expr())
                ),
                clear_state_program=compile_source(
                    client, compile_expr(self.clear_expr())
                ),
                global_state_schema=global_state_schema,
                local_state_schema=local_state_schema,
                global_state=global_state,
            ),
        )
