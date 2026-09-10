class DatabaseServiceError(Exception):
    """A safe, retryable database failure exposed to API clients."""

    code = "database:unavailable"
    status_code = 503
    message = "The database is temporarily unavailable."

    def __init__(self) -> None:
        super().__init__(self.message)


class DatabaseTimeoutError(DatabaseServiceError):
    code = "database:timeout"
    status_code = 504
    message = "The database request timed out."


class DatabaseUnavailableError(DatabaseServiceError):
    pass
