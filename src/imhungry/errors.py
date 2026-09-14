"""Safe application errors shared by the HTTP and tool adapters."""


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class NotFound(AppError):
    def __init__(self):
        super().__init__("not_found", "Resource not found", 404)


class Conflict(AppError):
    def __init__(self, message="Resource changed or request is already in progress"):
        super().__init__("conflict", message, 409)
