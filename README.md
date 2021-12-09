# Algo App Dev

Utilities to help in the development of PyTeal contracts for Algorand.
Documentation: <https://gmcgoldr.github.io/algo-app-dev/>.

## Installation

You should install the package globally so that using commands run with `sudo -u algorand` can access to the package and binaries.

```bash
sudo pip install -U algo-app-dev
```

### Pre-requisits

In this documentation, it is assumed that you are running an algorand node in an Ubuntu environment.

You can install algorand with following these commands:

```bash
sudo apt-get update
sudo apt-get install -y gnupg2 curl software-properties-common
curl -O https://releases.algorand.com/key.pub
sudo apt-key add key.pub
rm -f key.pub
sudo add-apt-repository "deb [arch=amd64] https://releases.algorand.com/deb/ stable main"
sudo apt-get update
sudo apt-get install algorand
```

## Command line utilities

The following command line utilities are isntalled with the package.
They help streamline some common system tasks realting to algorand devleopment:

- `aad-make-node`: this command can be used to setup a private, and private development node
- `aad-run-node`: this command can be used to start or stop node daemons

## Modules

The following is a brief overview of the package's functionality and organization:

### clients

The `clients` module contains a few utilities to help manage the `algod` and `kmd` daeomon clients.

There are also utilities to help extract key-value information from global and local state queries.

### transactions

The `transactions` module contains utilities to help create and manage transactions.

### apps

The `apps` module contains utilities and classes to help construct and manage stateful applications (stateful smart contracts).
This is the core of the package.

Most the app development work utilizes two classes: the `State` and `AppBuilder` classes.
These help reduce the amount of boiler-plate needed to create functional `pyteal` expressions.

Manually managing the app's state is very error prone.
The interface provided by `State` and its derived `StateGlobal`, `StateGlobalExternal`, `StateLocal` and `StateLocalExternal` can reduce these errors.

Here is an example of a very simple app with a global counter.
Every time a (no-op) call is made with the argument "count", it increments the counter.

```python
import pyteal as tl
from algosdk.util import algos_to_microalgos
from algoappdev import apps, clients, dryruns, transactions, utils

# build the clients
algod_client = clients.build_algod_local_client(NODE_PATH)
kmd_client = clients.build_kmd_local_client(NODE_PATH)
# fund an account on the private net which can be used to transact
funded_account, txid = transactions.fund_from_genesis(
    algod_client, kmd_client, algos_to_microalgos(1)
)
# wait for the funding to go through
transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)

# define the state: a single global counter which defaults to 0
state = apps.StateGlobal([apps.State.KeyInfo("counter", tl.Int, tl.Int(0))])
# define the logic: invoking with the argument "count" increments the counter
app_builder = apps.AppBuilder(
    invocations={
        "count": tl.Seq(
            state.set("counter", state.get("counter") + tl.Int(1)),
            tl.Return(tl.Int(1)),
        ),
    },
    global_state=state,
)

# deploy the application
txn = app_builder.create_txn(
    algod_client, funded_account.address, algod_client.suggested_params()
)
txid = algod_client.send_transaction(txn.sign(funded_account.key))
# the app id and address can be derived from the transaction output
txn_info = transactions.get_confirmed_transaction(algod_client, txid, WAIT_ROUNDS)
app_meta = utils.AppMeta.from_result(txn_info)
print(app_meta)
```

The resulting `app_meta` object:

```python
AppMeta(app_id=1, address='...')
```

### dryruns

The `dryruns` module contais utilities to help send dry runs to a node,
and parse the results.

Here is how the `dryruns` utilities could be used to test the contract:

```python
# build a dryrun request containing the entire state needed to call the app
result = algod_client.dryrun(
    dryruns.AppCallCtx()
    # use the app's programs and schema
    .with_app(app_builder.build_application(algod_client, 1))
    # add a transaction calling the app with the given arg
    .with_txn_call(args=[b"count"])
    .build_request()
)
for item in dryruns.get_trace(result):
    print(item)
for delta in dryruns.get_global_deltas(result):
    print(delta)
```

The last few lines of the stack trace should resemble:

```
55 :: app_global_get :: [b'counter'  , 0           ]
56 :: intc_0 // 1    :: [b'counter'  , 0           , 1           ]
57 :: +              :: [b'counter'  , 1           ]
58 :: app_global_put :: []
59 :: intc_0 // 1    :: [1           ]
81 :: return         :: [1           ]
```

The resulting state delta:

```python
KeyDelta(key=b'counter', value=1)
```

## Testing

NOTE: in order to use the testing functionality, you must install the `dev` dependencies.
This is done with the command:

```bash
sudo pip install -U algo-app-dev[dev]
```

You should run tests as the `algorand` user so that the tests can access the local daemons.
The daemon access token file can be ready only by the `algorand` user.

Start the daemons before testing, and optionally stop them after the tests run.

The tests make calls to the node, which is slow. There are two mitigations for this:
using the dev node, and using the `pytest-xdist` plugin for pytest to parallelize the test.

The dev node creates a new block for every transaction, meaning that there is no need to wait for consensus.
Whereas testing with `private_dev` can take a 10s of seconds,
testing with `pivate` takes 10s of minutes.

The flag `-n X` can be used to split the tests into that many parallel processes.

```bash
sudo -u algorand aad-run-node private_dev start
sudo -u algorand pytest -n 4 tests/
sudo -u algorand aad-run-node private_dev stop
```

### PyTest envioronment

The module `algoappdev.testing` contains some `pytest` fixutres that are widely applicable.
If you want to make those fixutres available to all your tests,
you can create a file `conftest.py` in your test root directory and write to it:

```python
# conftest.py
from algoappdev.testing import *
```

It also exposes two variables which can be configured through environment variables:

- `NODE_DIR`: this should be the path to the node data to work with.
- `WAIT_ROUNDS`: this should be set to the maximun number of rounds to await transaction confirmations.

Both are read from the environment varible with corresponding name prefixed with `AAD_`.

`NODE_DIR` defaults to the private dev node data path.
If your system is configured differently, you will need to set this accordingly.

`WAIT_ROUNDS` defaults to 1, because when interacting with a dev node transactions are immediately committed.
If doing integration tests with a non-dev node,
this should be increased to give time for transactions to complete before moving onto another test.
