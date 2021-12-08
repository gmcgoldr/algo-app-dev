import shutil
import subprocess
from pathlib import Path

import pkg_resources


def main(network: str, path: Path, force: bool):
    path: Path = path / network

    if force:
        shutil.rmtree(str(path), ignore_errors=True)

    elif path.is_dir():
        if input("Overwrite [y/n]?").strip() == "y":
            shutil.rmtree(str(path), ignore_errors=True)
        else:
            print("Aborting")
            return

    template_path = Path(
        pkg_resources.resource_filename("algoappdev", f"data/network_{network}.json")
    )

    subprocess.call(
        [
            "goal",
            "network",
            "create",
            "--rootdir",
            str(path),
            "--network",
            network,
            "--template",
            str(template_path),
        ]
    )

    if network == "private_dev":
        subprocess.call(
            [
                "algocfg",
                "-d",
                str(path / "Primary"),
                "set",
                "-p",
                "EnableDeveloperAPI",
                "-v",
                "true",
            ]
        )


def main_args():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("network", choices=("private", "private_dev"))
    # default data path is be the `nets` directory in the algorand home
    parser.add_argument("--path", type=Path, default=Path("/var/lib/algorand/nets"))
    parser.add_argument("-f", "--force", action="store_true")
    args = parser.parse_args()

    main(**vars(args))


if __name__ == "__main__":
    main_args()
