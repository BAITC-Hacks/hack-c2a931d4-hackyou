class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, issues: list | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.issues = issues or []
        super().__init__(message)
