from typing import Dict, NamedTuple

import algosdk as ag

ZERO_ADDRESS = ag.encoding.encode_address(bytes(32))


class PyTealUtilsError(Exception):
    pass


class AccountMeta(NamedTuple):
    key: str
    address: str


class AppMeta(NamedTuple):
    app_id: int
    address: str

    @staticmethod
    def from_result(result: Dict) -> "AppMeta":
        app_id = result.get("application-index", None)
        if app_id is None:
            return None
        address = ag.encoding.encode_address(
            ag.encoding.checksum(b"appID" + app_id.to_bytes(8, "big"))
        )
        return AppMeta(app_id=app_id, address=address)
