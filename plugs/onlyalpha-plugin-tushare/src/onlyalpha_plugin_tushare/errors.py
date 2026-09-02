class OnlyTushareError(RuntimeError):
    """Structured vendor error whose message never contains credentials."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")
