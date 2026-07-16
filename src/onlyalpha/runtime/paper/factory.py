from onlyalpha.runtime.factory import OnlyUnsupportedRuntimeFactory


class OnlyPaperRuntimeFactory(OnlyUnsupportedRuntimeFactory):
    def __init__(self) -> None:
        super().__init__("PAPER")
