# Question Bank Web UI

An optional, lightweight browser interface for `question-bank`. It provides interactive practice, search, and progress tracking for users who prefer a web UI over the command-line interface or Hermes tool plugin.

Deleting `web/` has no effect on the `question-search` CLI or `question-bank-mcp` server.

## Running

Run the web server using `uv`:

```bash
web/start.sh   # loads the Study profile .env (OPENROUTER_API_KEY); or: uv run --extra web python web/server.py
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `QUESTION_BANK_WEB_HOST` | Host address to bind the web server | `127.0.0.1` |
| `QUESTION_BANK_WEB_PORT` | Port number to listen on | `8780` |
| `QUESTION_BANK_ROOT` | Absolute or relative path to question-bank root | Parent of `web/` |
| `QUESTION_BANK_USER` | Active user name for CLI/MCP fallback | `marcos` |

## Data Locations

- **Questions**: Read directly from `questions/*.json`. Practice and browse require no Qdrant or external APIs.
- **Answer Logs**: Stored per user in `data/users/<user>/answers.jsonl`.
- **Assets**: Images referenced in question stems or options are served from `assets/`.

## API Endpoints

All API endpoints return JSON payloads.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/users` | List existing users with folders in `data/users/` |
| `POST` | `/api/users` | Create a new user folder (`{"name": "username"}`) |
| `GET` | `/api/questions` | Query questions index with optional `exam`, `year`, `tag`, and `status` (`active` or `all`) filters |
| `GET` | `/api/questions/{id}` | Read question content with `answer` and `rubric` redacted |
| `POST` | `/api/u/{user}/sessions` | Create a practice session (`count`, `exam`, `tag`, `only_unseen`, `include_suspended`, `weakest`) |
| `POST` | `/api/u/{user}/answer` | Submit attempt (`question_id`, `session_id`, `given_answer`, optional `time_spent`, `self_grade`); server grades and records attempt |
| `GET` | `/api/u/{user}/session/{session_id}` | Retrieve recorded attempts for a session |
| `GET` | `/api/u/{user}/stats` | Retrieve overall accuracy, worst-first topic breakdowns, and 182-day activity data |
| `GET` | `/api/search` | Semantic vector search query (`q`, `exam`, `year`, `tag`, `limit`). Returns 503 if Qdrant or embedding is offline |

## Security

- **Loopback binding**: The server defaults to `127.0.0.1` and should never be bound to a public interface without authentication.
- **Remote access**: For secure remote access across devices, use a secure mesh network such as Tailscale.
- **Content Security Policy**: The application serves restrictive security headers (`Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:` and `X-Content-Type-Options: nosniff`).
- **Path traversal protection**: All question IDs, asset paths, and usernames are validated to prevent directory traversal.
