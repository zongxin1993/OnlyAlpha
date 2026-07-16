from onlyalpha.runtime.factory import OnlyUnsupportedRuntimeFactory


class OnlyResearchRuntimeFactory(OnlyUnsupportedRuntimeFactory):
    def __init__(self) -> None:
        super().__init__("RESEARCH")
