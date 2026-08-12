class CommandRejected(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        message = code if not detail else "{}: {}".format(code, detail)
        super().__init__(message)
