from algosdk.v2client.models.teal_key_value import TealKeyValue
from algosdk.v2client.models.teal_value import TealValue

from algoappdev import utils


def test_app_info_builds_from_result():
    result = {"application-index": 0}
    info = utils.AppMeta.from_result(result)
    assert info.app_id == 0
    assert info.address == "6X7XJO6FX3SHUK2OUL46QBQDSNO67RAFK6O73KJD4IVOMTSOIYANOIVWNU"


def test_from_value_decodes_values():
    assert utils.from_value({"type": 1, "bytes": "YQ==", "uint": None}) == b"a"
    assert utils.from_value({"type": 2, "bytes": b"", "uint": 1}) == 1


def test_to_value_encodes_values():
    assert utils.to_value(b"a") == TealValue(type=1, bytes="YQ==", uint=None)
    assert utils.to_value(1) == TealValue(type=2, bytes=None, uint=1)


def test_to_key_value_encodes_key():
    assert utils.to_key_value(b"a", 1) == TealKeyValue(
        key="YQ==", value=TealValue(type=2, bytes=None, uint=1)
    )
