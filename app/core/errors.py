from dataclasses import dataclass


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int
    retryable: bool = False

    def __post_init__(self) -> None:
        super().__init__(self.message)
