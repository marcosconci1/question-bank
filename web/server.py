"""Web server and JSON API for the question-bank module."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import sys
from typing import Any
import uuid

MODULE_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = MODULE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
import uvicorn

from question_bank import answers


STATIC_DIR = Path(__file__).resolve().parent / "static"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


class BankManager:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.questions_dir = (self.root / "questions").resolve()
        self.assets_dir = (self.root / "assets").resolve()
        self._mtime = -1.0
        self._questions: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}

    def get_questions(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        if not self.questions_dir.is_dir():
            return [], {}
        mtime = self.questions_dir.stat().st_mtime
        if mtime != self._mtime:
            loaded_list: list[dict[str, Any]] = []
            by_id: dict[str, dict[str, Any]] = {}
            for path in sorted(self.questions_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                qid = data.get("id") or path.stem
                summary = {
                    "id": qid,
                    "exam": data.get("exam"),
                    "year": data.get("year"),
                    "number": data.get("number"),
                    "type": data.get("type", "mc"),
                    "tags": list(data.get("tags") or []),
                    "status": data.get("status", "active"),
                }
                loaded_list.append(summary)
                by_id[qid] = data
            self._mtime = mtime
            self._questions = loaded_list
            self._by_id = by_id
        return self._questions, self._by_id

    def get_single_question(self, qid: str) -> dict[str, Any] | None:
        if not qid or Path(qid).name != qid:
            return None
        target = (self.questions_dir / f"{qid}.json").resolve()
        if target.parent != self.questions_dir or not target.is_file():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None


def _validate_user_or_response(user: str, root: Path) -> Response | None:
    try:
        answers.validate_user(user)
    except ValueError as exc:
        return JSONResponse({"error": "invalid_user", "message": str(exc)}, status_code=400)
    user_dir = root / "data" / "users" / user
    if not user_dir.is_dir():
        return JSONResponse(
            {"error": "user_not_found", "message": f"User '{user}' not found"}, status_code=404
        )
    return None


def create_app(bank_root: Path | None = None) -> Starlette:
    root = (
        bank_root
        or Path(os.environ.get("QUESTION_BANK_ROOT", str(Path(__file__).resolve().parent.parent)))
    ).resolve()
    bank = BankManager(root)

    async def index(_: Request) -> Response:
        index_file = STATIC_DIR / "index.html"
        return FileResponse(index_file)

    async def serve_asset(request: Request) -> Response:
        subpath = request.path_params.get("path", "")
        if not subpath:
            return JSONResponse({"error": "not_found"}, status_code=404)
        target = (bank.assets_dir / subpath).resolve()
        if not target.is_relative_to(bank.assets_dir) or not target.is_file():
            return JSONResponse({"error": "asset_not_found"}, status_code=404)
        return FileResponse(target)

    async def get_users(_: Request) -> Response:
        users = answers.list_users(root)
        return JSONResponse({"users": users})

    async def post_user(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_json"}, status_code=400)
        name = body.get("name")
        if not isinstance(name, str):
            return JSONResponse({"error": "invalid_user", "message": "name required"}, status_code=400)
        try:
            answers.create_user(root, name)
        except ValueError as exc:
            return JSONResponse({"error": "invalid_user", "message": str(exc)}, status_code=400)
        return JSONResponse({"name": name}, status_code=201)

    async def get_questions(request: Request) -> Response:
        status_filter = request.query_params.get("status", "active").lower()
        exam_filter = request.query_params.get("exam")
        year_filter = request.query_params.get("year")
        tag_filter = request.query_params.get("tag")

        questions, _ = bank.get_questions()
        filtered: list[dict[str, Any]] = []
        for q in questions:
            if status_filter != "all" and q.get("status") != "active":
                continue
            if exam_filter and (q.get("exam") or "").lower() != exam_filter.lower():
                continue
            if year_filter:
                try:
                    if q.get("year") != int(year_filter):
                        continue
                except ValueError:
                    continue
            if tag_filter and tag_filter not in (q.get("tags") or []):
                continue
            filtered.append(q)
        return JSONResponse(filtered)

    async def get_question(request: Request) -> Response:
        qid = request.path_params.get("id", "")
        question = bank.get_single_question(qid)
        if question is None:
            return JSONResponse({"error": "question_not_found"}, status_code=404)
        safe_copy = dict(question)
        safe_copy.pop("answer", None)
        safe_copy.pop("rubric", None)
        return JSONResponse(safe_copy)

    async def create_session(request: Request) -> Response:
        user = request.path_params.get("user", "")
        user_err = _validate_user_or_response(user, root)
        if user_err:
            return user_err

        try:
            body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        except Exception:
            body = {}

        count = int(body.get("count", 10))
        exam_filter = body.get("exam")
        tag_filter = body.get("tag")
        only_unseen = bool(body.get("only_unseen", False))
        include_suspended = bool(body.get("include_suspended", False))
        weakest = bool(body.get("weakest", False))

        questions, _ = bank.get_questions()
        user_answers = answers.read_answers(answers.answers_path(root, user))
        answered_ids = {a.get("question_id") for a in user_answers}

        pool = [
            q for q in questions
            if (include_suspended or q.get("status") == "active")
            and (not exam_filter or (q.get("exam") or "").lower() == exam_filter.lower())
            and (not tag_filter or tag_filter in (q.get("tags") or []))
            and (not only_unseen or q.get("id") not in answered_ids)
        ]

        if weakest:
            tag_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
            for a in user_answers:
                c = 1 if a.get("is_correct") is True else 0
                for t in a.get("tags") or []:
                    tag_stats[t]["total"] += 1
                    tag_stats[t]["correct"] += c
            eligible_tags = {
                t: stats["correct"] / stats["total"]
                for t, stats in tag_stats.items()
                if stats["total"] >= 1
            }
            if eligible_tags:
                min_acc = min(eligible_tags.values())
                worst_tags = {t for t, acc in eligible_tags.items() if acc == min_acc}
                weak_pool = [q for q in pool if any(t in worst_tags for t in (q.get("tags") or []))]
                if weak_pool:
                    pool = weak_pool

        chosen = random.sample(pool, min(count, len(pool))) if pool else []
        session_id = uuid.uuid4().hex
        return JSONResponse({"session_id": session_id, "question_ids": [q["id"] for q in chosen]})

    async def post_answer(request: Request) -> Response:
        user = request.path_params.get("user", "")
        user_err = _validate_user_or_response(user, root)
        if user_err:
            return user_err

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_json"}, status_code=400)

        qid = body.get("question_id")
        session_id = body.get("session_id")
        given_answer = body.get("given_answer", "")
        if not qid or not session_id:
            return JSONResponse({"error": "missing_fields"}, status_code=400)

        question = bank.get_single_question(qid)
        if question is None:
            return JSONResponse({"error": "question_not_found"}, status_code=404)

        qtype = question.get("type", "mc")
        rubric = None
        if qtype == "mc":
            correct_answer = str(question.get("answer", "")).strip().upper()
            student_answer = str(given_answer).strip().upper()
            is_correct = bool(student_answer and student_answer == correct_answer)
        elif qtype == "discursive":
            self_grade = body.get("self_grade")
            if self_grade not in {"correct", "partial", "wrong"}:
                return JSONResponse(
                    {"error": "invalid_self_grade", "message": "self_grade must be correct, partial, or wrong"},
                    status_code=400,
                )
            is_correct = (self_grade == "correct")
            correct_answer = question.get("answer")
            rubric = question.get("rubric")
        else:
            correct_answer = str(question.get("answer", "")).strip().upper()
            student_answer = str(given_answer).strip().upper()
            is_correct = bool(student_answer and student_answer == correct_answer)
            rubric = question.get("rubric")

        req_record: dict[str, Any] = {
            "question_id": qid,
            "session_id": session_id,
            "given_answer": str(given_answer),
            "is_correct": is_correct,
        }
        if "time_spent" in body and body["time_spent"] is not None:
            try:
                req_record["time_spent"] = int(body["time_spent"])
            except (ValueError, TypeError):
                return JSONResponse({"error": "invalid_time_spent"}, status_code=400)

        try:
            record = answers.record_answer(root, user, req_record)
        except ValueError as exc:
            if "already recorded" in str(exc).lower():
                return JSONResponse(
                    {"error": "already_recorded", "message": str(exc)}, status_code=409
                )
            return JSONResponse({"error": "invalid_record", "message": str(exc)}, status_code=400)

        resp: dict[str, Any] = {
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "record": record,
        }
        if rubric is not None:
            resp["rubric"] = rubric
        return JSONResponse(resp)

    async def get_session(request: Request) -> Response:
        user = request.path_params.get("user", "")
        user_err = _validate_user_or_response(user, root)
        if user_err:
            return user_err

        session_id = request.path_params.get("session_id", "")
        all_records = answers.read_answers(answers.answers_path(root, user))
        matching = [r for r in all_records if r.get("session_id") == session_id]
        return JSONResponse(matching)

    async def get_stats(request: Request) -> Response:
        user = request.path_params.get("user", "")
        user_err = _validate_user_or_response(user, root)
        if user_err:
            return user_err

        records = answers.read_answers(answers.answers_path(root, user))
        total = len(records)
        correct = sum(1 for r in records if r.get("is_correct") is True)
        accuracy = round(correct / total, 4) if total > 0 else 0.0

        by_tag_map: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
        for r in records:
            is_c = 1 if r.get("is_correct") is True else 0
            # Group by topic (second tag level); fall back to the area tag.
            rtags = r.get("tags") or []
            for t in (rtags[1:2] or rtags[:1]):
                by_tag_map[t]["total"] += 1
                by_tag_map[t]["correct"] += is_c

        by_tag = []
        for t, cnt in by_tag_map.items():
            t_total = cnt["total"]
            t_correct = cnt["correct"]
            t_acc = round(t_correct / t_total, 4) if t_total > 0 else 0.0
            seg = t.split("/")[-1]
            label = seg.replace("-", " ").strip().capitalize()
            by_tag.append({
                "tag": t,
                "label": label,
                "total": t_total,
                "correct": t_correct,
                "accuracy": t_acc,
            })
        by_tag.sort(key=lambda x: (x["accuracy"], -x["total"], x["tag"]))

        today = datetime.now(timezone.utc).date()
        date_counts: dict[str, int] = defaultdict(int)
        for r in records:
            ts = r.get("timestamp")
            if isinstance(ts, str) and len(ts) >= 10:
                date_counts[ts[:10]] += 1

        activity = []
        for i in range(182):
            d = (today - timedelta(days=181 - i)).isoformat()
            activity.append({"date": d, "count": date_counts[d]})

        return JSONResponse({
            "total": total,
            "correct": correct,
            "accuracy": accuracy,
            "by_tag": by_tag,
            "activity": activity,
        })

    async def search(request: Request) -> Response:
        query = request.query_params.get("q", "").strip()
        if not query:
            return JSONResponse([])

        limit_raw = request.query_params.get("limit", "10")
        try:
            limit = max(1, min(50, int(limit_raw)))
        except ValueError:
            limit = 10

        exam = request.query_params.get("exam") or None
        year = request.query_params.get("year")
        tag = request.query_params.get("tag")

        year_range = None
        if year:
            try:
                y = int(year)
                year_range = (y, y)
            except ValueError:
                pass

        tags = [tag.strip()] if tag and tag.strip() else None

        try:
            from question_search import embed, store
            vectors = embed.embed([query])
            if not vectors:
                raise ValueError("Embedding returned empty result")
            raw_results = store.search_questions(
                query_vector=vectors[0],
                limit=limit,
                status="active",
                exam=exam,
                year_range=year_range,
                tags=tags,
            )
            results = [
                {
                    "id": r["id"],
                    "score": r["score"],
                    "exam": r.get("exam"),
                    "year": r.get("year"),
                    "number": r.get("number"),
                    "tags": r.get("tags") or [],
                    "snippet": r.get("preview") or "",
                }
                for r in raw_results
            ]
            return JSONResponse(results)
        except Exception as exc:
            return JSONResponse(
                {"error": "search_unavailable", "message": str(exc)},
                status_code=503,
            )

    routes = [
        Route("/", endpoint=index),
        Route("/api/users", endpoint=get_users, methods=["GET"]),
        Route("/api/users", endpoint=post_user, methods=["POST"]),
        Route("/api/questions", endpoint=get_questions, methods=["GET"]),
        Route("/api/questions/{id:str}", endpoint=get_question, methods=["GET"]),
        Route("/api/u/{user:str}/sessions", endpoint=create_session, methods=["POST"]),
        Route("/api/u/{user:str}/answer", endpoint=post_answer, methods=["POST"]),
        Route("/api/u/{user:str}/session/{session_id:str}", endpoint=get_session, methods=["GET"]),
        Route("/api/u/{user:str}/stats", endpoint=get_stats, methods=["GET"]),
        Route("/api/search", endpoint=search, methods=["GET"]),
        Route("/assets/{path:path}", endpoint=serve_asset, methods=["GET"]),
        Mount("/static", app=StaticFiles(directory=STATIC_DIR), name="static"),
    ]

    return Starlette(
        routes=routes,
        middleware=[Middleware(SecurityHeadersMiddleware)],
    )


app = create_app()


def main() -> None:
    host = os.environ.get("QUESTION_BANK_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("QUESTION_BANK_WEB_PORT", "8780"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
