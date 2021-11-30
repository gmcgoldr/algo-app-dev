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

```bash
sudo -u algorand ptu-run-node private_dev start
sudo -u algorand
    ALGORAND_DATA=/var/lib/algorand/nets/private_dev/Primary \
    pytest --tb=short tests/
sudo -u algorand ptu-run-node private_dev stop
```
