from onlyalpha.runtime.factory import OnlyUnsupportedRuntimeFactory


class OnlyShadowRuntimeFactory(OnlyUnsupportedRuntimeFactory):
    def __init__(self) -> None:
        super().__init__("SHADOW")
