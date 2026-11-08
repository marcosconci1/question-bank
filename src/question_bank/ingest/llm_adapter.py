"""PDF question extraction with a bounded structured-output repair loop.

Structured-output retry loop adapted from jxnl/instructor (MIT).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

import httpx
import pymupdf

from question_search import config as search_config

from .manifest import Source

DEFAULT_EXTRACT_MODEL = "openai/gpt-4o-mini"
OPENROUTER_CHAT_URL = search_config.EMBEDDING_BASE_URL.rstrip("/") + "/chat/completions"


def _slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in folded if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "exam"


def _validate_response(raw: str) -> list[dict[str, Any]]:
    """Parse strict JSON and validate the extraction-level question shape."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
    if not isinstance(payload, list):
        raise ValueError("response must be a JSON list")
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        prefix = f"item {index}"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} must be an object")
        number = item.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise ValueError(f"{prefix}.number must be an integer")
        stem = item.get("stem")
        if not isinstance(stem, str) or not stem.strip():
            raise ValueError(f"{prefix}.stem must be a non-empty string")
        options = item.get("options")
        if not isinstance(options, dict) or not options:
            raise ValueError(f"{prefix}.options must be a non-empty object")
        if any(key not in {"A", "B", "C", "D", "E"} for key in options):
            raise ValueError(f"{prefix}.options keys must be A through E")
        if any(not isinstance(value, str) or not value.strip() for value in options.values()):
            raise ValueError(f"{prefix}.options values must be non-empty strings")
        answer = item.get("answer")
        if answer is not None and (not isinstance(answer, str) or answer not in options):
            raise ValueError(f"{prefix}.answer must be one of its option keys or null")
        validated.append({"number": number, "stem": stem.strip(), "options": options, "answer": answer})
    return validated


class PdfLlmAdapter:
    """Extract questions from text-layer PDFs using OpenRouter chat completions.

    ``llm_client`` may be a callable accepting a prompt string, or an object
    exposing ``complete(prompt)``. Production calls use the OpenRouter API.
    ``page_accounting`` contains one outcome per source page after each read.
    """

    def __init__(self, llm_client: Any | None = None, model: str | None = None):
        self.llm_client = llm_client
        self.model = model or os.environ.get("QUESTION_EXTRACT_MODEL", DEFAULT_EXTRACT_MODEL)
        self.page_accounting: list[dict[str, Any]] = []

    def _request(self, prompt: str) -> str:
        if self.llm_client is not None:
            if callable(self.llm_client):
                result = self.llm_client(prompt)
            else:
                result = self.llm_client.complete(prompt)
            if not isinstance(result, str):
                raise TypeError("fake LLM client must return response text")
            return result

        key = search_config.OPENROUTER_API_KEY
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    OPENROUTER_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "temperature": 0,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not reach OpenRouter chat API at {OPENROUTER_CHAT_URL}: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                f"OpenRouter chat API returned HTTP {response.status_code} from "
                f"{OPENROUTER_CHAT_URL}: {response.text[:200]}"
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to parse OpenRouter chat response: {exc}") from exc
        if not isinstance(content, str):
            raise RuntimeError("OpenRouter chat response content was not text")
        return content

    @staticmethod
    def _prompt(source: Source, batch: list[tuple[int, str]], repair_error: str | None = None,
                previous_response: str | None = None) -> str:
        page_text = "\n\n".join(f"--- PAGE {page_number} ---\n{text}" for page_number, text in batch)
        prompt = (
            "Extract every multiple-choice question found in these exam pages. "
            "Return STRICT JSON only: a list of objects with number (integer), stem (string), "
            "options (object keyed by A through E, or fewer available letters), and answer "
            "(the option letter or null when no answer is printed). Return [] when the pages "
            "contain no questions. Preserve wording and do not invent missing text.\n"
            f"Exam context: {source.exam}, year {source.year}.\n"
            'Worked example 1: “1. Which is true? (A) Yes (B) No. Answer: A” → '
            '[{"number":1,"stem":"Which is true?","options":{"A":"Yes","B":"No"},"answer":"A"}]\n'
            'Worked example 2: “Questions start on the next page.” → []\n'
        )
        if repair_error is not None:
            prompt += (
                "Your previous response failed validation. Repair it and return the complete "
                f"JSON list. Validator error: {repair_error}\nPrevious response:\n{previous_response}\n"
            )
        return prompt + "Pages:\n" + page_text

    def read(self, source: Source) -> Iterable[dict[str, Any]]:
        batch_pages = source.options.get("batch_pages", 4)
        if not isinstance(batch_pages, int) or isinstance(batch_pages, bool) or batch_pages < 1:
            raise ValueError("batch_pages must be a positive integer")
        self.page_accounting = []
        with pymupdf.open(str(source.path)) as document:
            pages = [(index + 1, page.get_text("text")) for index, page in enumerate(document)]

        for start in range(0, len(pages), batch_pages):
            batch = pages[start : start + batch_pages]
            page_start, page_end = batch[0][0], batch[-1][0]
            nonempty = [(number, text) for number, text in batch if text.strip()]
            if not nonempty:
                self.page_accounting.extend(
                    {"page": number, "status": "empty"} for number, _ in batch
                )
                continue
            first_prompt = self._prompt(source, nonempty)
            try:
                raw = self._request(first_prompt)
                try:
                    questions = _validate_response(raw)
                except ValueError as initial_error:
                    repaired = self._request(
                        self._prompt(source, nonempty, str(initial_error), raw)
                    )
                    try:
                        questions = _validate_response(repaired)
                    except ValueError as repair_error:
                        raise ValueError(f"repair_failed: {repair_error}") from repair_error
            except ValueError as exc:
                yield {
                    "_ingest_error": f"pdf_llm_invalid_batch:{exc}",
                    "page_range": [page_start, page_end],
                    "source_id": source.id,
                }
                self.page_accounting.extend(
                    {"page": number, "status": "quarantined", "reason": str(exc)}
                    for number, _ in batch
                )
                continue

            if not questions:
                self.page_accounting.extend(
                    {"page": number, "status": "empty"} for number, _ in batch
                )
                continue
            self.page_accounting.extend(
                {
                    "page": number,
                    "status": "yielded-candidate" if text.strip() else "empty",
                }
                for number, text in batch
            )
            for question in questions:
                letter_keys = sorted(question["options"])
                mapped_answer = (
                    chr(ord("A") + letter_keys.index(question["answer"]))
                    if question["answer"] is not None else None
                )
                exam_slug = _slug(source.exam)
                number = question["number"]
                yield {
                    "id": f"{exam_slug}-{source.year}-{_slug(source.id)}-{number}",
                    "type": "mc",
                    "exam": source.exam,
                    "year": source.year,
                    "number": number,
                    "stem": question["stem"],
                    "options": [question["options"][key] for key in letter_keys],
                    "answer": mapped_answer,
                    "source": f"{source.exam.upper()} {source.year}, question {number}",
                    "tags": source.options.get("tags", []),
                    "status": "active",
                    "provenance": {
                        "source_id": source.id,
                        "adapter": "pdf-llm",
                        "model": self.model,
                        "page_range": [page_start, page_end],
                    },
                }
