"""Configuration for question-search, loaded from environment variables."""
import os
from pathlib import Path

QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6343")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "64"))

REPO_ROOT = Path(__file__).resolve().parents[2]
BANK_ROOT = Path(os.environ.get("QUESTION_BANK_ROOT", str(REPO_ROOT)))
QUESTIONS_DIR = BANK_ROOT / "questions"
CONTEXTS_DIR = BANK_ROOT / "contexts"

STATE_DIR = Path(os.environ.get("QUESTION_BANK_STATE", str(Path.home() / ".local/share/question-bank")))
LEDGER_PATH = STATE_DIR / "ledger.json"

COLLECTION = os.environ.get("QUESTION_BANK_COLLECTION", "questions")
