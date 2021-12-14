"""Run a node connected to a local private network."""

import subprocess
from pathlib import Path


def main(path: Path, action: str):
    network = path.name
    networks = {"private", "private_dev"}
    if network not in networks:
        raise ValueError(f"network path must end in: {networks}")
    subprocess.call(["goal", "-d", str(path / "Primary"), "node", action])
    subprocess.call(["goal", "-d", str(path / "Primary"), "kmd", action])


def main_args():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("action", choices=("start", "stop"))
    args = parser.parse_args()

    main(**vars(args))


if __name__ == "__main__":
    main_args()
