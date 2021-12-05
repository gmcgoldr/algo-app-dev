import subprocess
from pathlib import Path


def main(network: str, path: Path, action: str):
    path = path / network / "Primary"
    subprocess.call(["goal", "-d", str(path), "node", action])
    subprocess.call(["goal", "-d", str(path), "kmd", action])


def main_args():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("network", choices=("private", "private_dev"))
    parser.add_argument("action", choices=("start", "stop"))
    # default data path is be the `nets` directory in the algorand home
    parser.add_argument("--path", type=Path, default=Path("/var/lib/algorand/nets"))
    args = parser.parse_args()

    main(**vars(args))


if __name__ == "__main__":
    main_args()
