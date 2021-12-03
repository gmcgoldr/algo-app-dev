from pyteal_utils import utils


def test_app_info_builds_from_result():
    result = {"application-index": 0}
    info = utils.AppMeta.from_result(result)
    assert info.app_id == 0
    assert info.address == "6X7XJO6FX3SHUK2OUL46QBQDSNO67RAFK6O73KJD4IVOMTSOIYANOIVWNU"
