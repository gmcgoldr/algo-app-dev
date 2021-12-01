# PyTeal Utils

Utilities to help in the development of PyTeal contracts for Algorand.

## Installation

You should install the package globally so that using commands run with `sudo -u algorand` can access to the package and binaries.

```bash
sudo pip install -U pyteal-utils
```

## Testing

You should test as the `algorand` account so that the test can access the local daemons.
The daemon access token file can be ready only by the `algorand` user.

Start the daemons before testing, and optionally stop them after the tests run.

The tests make calls to the node, which is slow. There are two mitigations for
this: using the dev node, and using the `pytest-xdist` plugin for pytest to
parallelize the test.

The dev node creates a new block for every transaction, meaning that there is
no need to wait for consensus. Whereas testing with `private_dev` can take a
10s of seconds, testing with `pivate` takes 10s of minutes.

If testing with `private`, then the `ALGORAND_WAIT_ROUNDS` environment variable
should be set. A value around 5 works well, allowing the network to process
transactions from the test before proceeding to the next step.

The flag `-n X` can be used to split the tests into that many parallel
processes.

```bash
sudo -u algorand ptu-run-node private_dev start
sudo -u algorand \
    ALGORAND_DATA=/var/lib/algorand/nets/private_dev/Primary \
    pytest --tb=short -n 4 tests/
sudo -u algorand ptu-run-node private_dev stop
```
