from onlyalpha.runtime.factory import OnlyUnsupportedRuntimeFactory


class OnlyLiveRuntimeFactory(OnlyUnsupportedRuntimeFactory):
    def __init__(self) -> None:
        super().__init__("LIVE")
