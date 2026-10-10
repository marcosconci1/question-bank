"""Error categories, exit codes, and exception classification for question-search."""
import json
import sys

EXIT_OK = 0
EXIT_INVALID_ARGS = 2
EXIT_CONFIG_ERROR = 3
EXIT_SERVICE_ERROR = 4
EXIT_INTERNAL_ERROR = 5

ERROR_EXIT_CODES = {
    "invalid_args": EXIT_INVALID_ARGS,
    "missing_api_key": EXIT_CONFIG_ERROR,
    "empty_bank": EXIT_CONFIG_ERROR,
    "qdrant_unreachable": EXIT_SERVICE_ERROR,
    "embedding_api_error": EXIT_SERVICE_ERROR,
    "internal_error": EXIT_INTERNAL_ERROR,
}

ALLOWED_EXIT_CODES = {
    EXIT_OK,
    EXIT_INVALID_ARGS,
    EXIT_CONFIG_ERROR,
    EXIT_SERVICE_ERROR,
    EXIT_INTERNAL_ERROR,
}


class QuestionSearchError(Exception):
    """Base error classified into the agent-facing CLI contract."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message

    @property
    def exit_code(self) -> int:
        return ERROR_EXIT_CODES.get(self.category, EXIT_INTERNAL_ERROR)


class MissingApiKeyError(QuestionSearchError):
    def __init__(self, message: str = "OPENROUTER_API_KEY is not set — configure it in the environment"):
        super().__init__("missing_api_key", message)


class EmptyBankError(QuestionSearchError):
    def __init__(self, message: str = "Question bank directory is empty or does not contain question JSON files"):
        super().__init__("empty_bank", message)


class InvalidArgsError(QuestionSearchError):
    def __init__(self, message: str):
        super().__init__("invalid_args", message)


class QdrantUnreachableError(QuestionSearchError):
    def __init__(self, message: str):
        super().__init__("qdrant_unreachable", message)


class EmbeddingApiError(QuestionSearchError):
    def __init__(self, message: str):
        super().__init__("embedding_api_error", message)


def _is_qdrant_exception(exc: BaseException) -> bool:
    """Check if exception originated from qdrant_client or grpc."""
    for klass in type(exc).__mro__:
        module = getattr(klass, "__module__", "") or ""
        if module.startswith("qdrant_client") or module.startswith("grpc"):
            return True
    return False


def _walk_causes(exc: BaseException):
    """Yield the exception and its causes/contexts chain."""
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify(exc: BaseException) -> tuple[str, str, int]:
    """Map any exception to (category, message, exit_code)."""
    for current in _walk_causes(exc):
        if isinstance(current, QuestionSearchError):
            return current.category, current.message, current.exit_code

    for current in _walk_causes(exc):
        if _is_qdrant_exception(current):
            return "qdrant_unreachable", f"Could not reach Qdrant: {current}", EXIT_SERVICE_ERROR

    for current in _walk_causes(exc):
        module = (getattr(type(current), "__module__", "") or "").split(".")[0]
        if module == "httpx":
            return "embedding_api_error", f"Embedding API request failed: {current}", EXIT_SERVICE_ERROR

    message = str(exc) or type(exc).__name__
    return "internal_error", message, EXIT_INTERNAL_ERROR


def emit(category: str, message: str, exit_code: int, stream=None) -> int:
    """Print single-line JSON error object to stderr and return exit code."""
    stream = stream if stream is not None else sys.stderr
    print(
        json.dumps({"error": category, "message": message, "exit_code": exit_code}, ensure_ascii=False),
        file=stream,
    )
    return exit_code


def report(exc: BaseException, stream=None) -> int:
    """Classify exc, emit as structured JSON, and return exit code."""
    category, message, exit_code = classify(exc)
    return emit(category, message, exit_code, stream=stream)
