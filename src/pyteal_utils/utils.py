import algosdk as ag

ZERO_ADDRESS = ag.encoding.encode_address(bytes(32))


class PyTealUtilsError(Exception):
    pass
