"""Unit and integration tests for the question-bank web module."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

import pytest
from starlette.testclient import TestClient

from question_bank import answers
from question_bank.tag_registry import bundled_tags
from web.server import create_app


APP_JS_PATH = MODULE_ROOT / "web" / "static" / "app.js"

_NODE_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');

const cfg = JSON.parse(process.argv[1]);
const appCode = fs.readFileSync(cfg.appJsPath, 'utf8');

const storage = new Map(Object.entries(cfg.initialStorage || {}));
const localStorage = {
  getItem(k) { return storage.has(String(k)) ? storage.get(String(k)) : null; },
  setItem(k, v) { storage.set(String(k), String(v)); },
  removeItem(k) { storage.delete(String(k)); },
  dump() { return Object.fromEntries(storage.entries()); },
};

const byId = new Map();
const alerts = [];

class ClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  add(...names) { names.forEach(n => n && this.set.add(n)); }
  remove(...names) { names.forEach(n => this.set.delete(n)); }
  contains(n) { return this.set.has(n); }
}

function registerTree(el) {
  if (el && el.id) byId.set(el.id, el);
  if (el && el.children) el.children.forEach(registerTree);
}

function decodeHtml(str) {
  return String(str)
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

function parseInnerHtml(html, ownerDoc) {
  const children = [];
  const clean = String(html);
  const tagRe = /<(select|input|h2|h3|p|div|a|button|span)\b([^>]*)>([\s\S]*?)<\/\1>|<(input)\b([^>]*)\/?>/gi;
  let match;
  while ((match = tagRe.exec(clean)) !== null) {
    const tag = (match[1] || match[4]).toUpperCase();
    const attrs = match[2] || match[5] || '';
    const inner = match[3] || '';
    const el = ownerDoc.createElement(tag);
    const idM = attrs.match(/\bid="([^"]*)"/i);
    if (idM) el.id = decodeHtml(idM[1]);
    const valM = attrs.match(/\bvalue="([^"]*)"/i);
    if (valM) el._value = decodeHtml(valM[1]);
    const typeM = attrs.match(/\btype="([^"]*)"/i);
    if (typeM) el.type = decodeHtml(typeM[1]);
    if (/\bchecked\b/i.test(attrs)) el.checked = true;
    if (tag === 'SELECT') {
      const optRe = /<option\b([^>]*)>([\s\S]*?)<\/option>/gi;
      let om;
      while ((om = optRe.exec(inner)) !== null) {
        const opt = ownerDoc.createElement('OPTION');
        const ov = om[1].match(/\bvalue="([^"]*)"/i);
        opt.value = ov ? decodeHtml(ov[1]) : decodeHtml(om[2].replace(/<[^>]+>/g, ''));
        opt.textContent = decodeHtml(om[2].replace(/<[^>]+>/g, ''));
        if (/\bselected\b/i.test(om[1])) opt.selected = true;
        el.appendChild(opt);
      }
    } else if (inner) {
      el.innerHTML = inner;
    }
    children.push(el);
  }
  return children;
}

class Element {
  constructor(tagName, ownerDoc) {
    this.tagName = String(tagName).toUpperCase();
    this.ownerDocument = ownerDoc;
    this._id = '';
    this._value = '';
    this._innerHTML = '';
    this._textContent = '';
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.listeners = {};
    this.classList = new ClassList(this);
    this.selected = false;
    this.checked = false;
    this.disabled = false;
  }
  get id() { return this._id; }
  set id(v) {
    this._id = String(v || '');
    if (this._id) byId.set(this._id, this);
  }
  set className(v) {
    this._className = String(v || '');
    this.classList.set = new Set(this._className.split(/\s+/).filter(Boolean));
  }
  get className() { return Array.from(this.classList.set).join(' '); }
  set innerHTML(v) {
    this._innerHTML = String(v ?? '');
    this._textContent = '';
    this.children = this._innerHTML ? parseInnerHtml(this._innerHTML, this.ownerDocument) : [];
    registerTree(this);
  }
  get innerHTML() { return this._innerHTML; }
  set textContent(v) {
    this._textContent = String(v ?? '');
    this._innerHTML = '';
    this.children = [];
  }
  get textContent() {
    if (this.children.length) {
      return this.children.map(c => c.textContent).filter(Boolean).join(' ');
    }
    if (this._innerHTML) {
      return decodeHtml(this._innerHTML.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim());
    }
    return this._textContent;
  }
  get value() {
    if (this.tagName === 'SELECT') {
      if (this._explicitValue !== undefined && this.children.some(c => c.value === this._explicitValue)) {
        return this._explicitValue;
      }
      const sel = this.children.find(c => c.selected);
      if (sel) return sel.value;
      return this.children[0] ? this.children[0].value : (this._explicitValue || '');
    }
    return this._value;
  }
  set value(v) {
    const sv = String(v ?? '');
    if (this.tagName === 'SELECT') {
      this._explicitValue = sv;
      this.children.forEach(c => { c.selected = (c.value === sv); });
    } else {
      this._value = sv;
    }
  }
  appendChild(child) {
    if (child && typeof child === 'object') {
      this.children.push(child);
      registerTree(child);
    }
    return child;
  }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'id') this.id = v;
  }
  getAttribute(k) { return this.attributes[k] ?? null; }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  async dispatchEvent(type, eventObj = {}) {
    const fns = this.listeners[type] || [];
    for (const fn of fns) {
      await fn({ target: this, preventDefault() {}, ...eventObj });
    }
  }
  click() { return this.dispatchEvent('click'); }
  focus() {}
  closest() { return null; }
}

const document = {
  documentElement: null,
  createElement(tag) { return new Element(tag, document); },
  createTextNode(text) {
    const span = new Element('TEXT', document);
    span.textContent = text;
    return span;
  },
  getElementById(id) { return byId.get(id) || null; },
  querySelectorAll(sel) {
    if (sel === '.nav-links a') return navLinks;
    return [];
  },
};
document.documentElement = document.createElement('html');

const appEl = document.createElement('main');
appEl.id = 'app';
const userSelect = document.createElement('select');
userSelect.id = 'user-select';
const themeToggle = document.createElement('button');
themeToggle.id = 'theme-toggle';
const navLinks = ['nav-practice', 'nav-search', 'nav-topics', 'nav-stats'].map(id => {
  const a = document.createElement('a');
  a.id = id;
  return a;
});

let inFlight = 0;
async function wrappedFetch(input, init) {
  inFlight += 1;
  try {
    const target = new URL(String(input), cfg.baseUrl).toString();
    return await fetch(target, init);
  } finally {
    inFlight -= 1;
  }
}

const winListeners = {};
let currentHash = cfg.initialHash || '#/';
const windowObj = {
  location: {
    get hash() { return currentHash; },
    set hash(v) {
      const next = String(v || '');
      if (next !== currentHash) {
        currentHash = next;
        queueMicrotask(() => {
          (winListeners['hashchange'] || []).forEach(fn => fn({ target: windowObj }));
        });
      }
    },
  },
  addEventListener(type, fn) { (winListeners[type] ||= []).push(fn); },
  prompt: () => cfg.promptValue ?? null,
  alert: (msg) => alerts.push(String(msg)),
  localStorage,
  document,
  fetch: wrappedFetch,
  URLSearchParams,
  setTimeout,
  clearTimeout,
};

async function settle() {
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 5));
    if (inFlight === 0) {
      await new Promise(r => setTimeout(r, 5));
      if (inFlight === 0) break;
    }
  }
}

function findButtonByText(root, label) {
  if (root.tagName === 'BUTTON' && root.textContent.includes(label)) return root;
  for (const ch of root.children || []) {
    const hit = findButtonByText(ch, label);
    if (hit) return hit;
  }
  return null;
}

(async () => {
  const ctx = vm.createContext({
    window: windowObj,
    document,
    localStorage,
    fetch: wrappedFetch,
    URLSearchParams,
    alert: windowObj.alert,
    prompt: windowObj.prompt,
    setTimeout,
    clearTimeout,
    console,
    Date,
    Math,
    JSON,
    Array,
    Object,
    Set,
    String,
    Number,
    Boolean,
    RegExp,
    Error,
    Promise,
    encodeURIComponent,
  });
  vm.runInContext(appCode, ctx, { filename: 'app.js' });
  await settle();

  if (cfg.action === 'start_practice') {
    const startBtn = findButtonByText(appEl, 'Start practice');
    if (startBtn) {
      await startBtn.click();
      await settle();
    }
  } else if (cfg.navigateHash) {
    windowObj.location.hash = cfg.navigateHash;
    await settle();
  }

  const out = {
    localStorage: localStorage.dump(),
    selectedUser: userSelect.value,
    userOptions: userSelect.children.map(o => ({
      value: o.value,
      text: o.textContent,
      selected: Boolean(o.selected),
    })),
    hash: windowObj.location.hash,
    appText: appEl.textContent,
    alerts,
  };
  process.stdout.write(JSON.stringify(out));
})().catch(err => {
  console.error(err);
  process.exit(1);
});
"""


@contextmanager
def _serve_test_app(app, *, fail_get_users: bool = False, fail_post_users: bool = False):
    client = TestClient(app)
    requests_log: list[dict[str, object]] = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return

        def _handle(self, method: str):
            length = int(self.headers.get("content-length") or 0)
            raw_body = self.rfile.read(length) if length > 0 else b""
            if fail_get_users and method == "GET" and self.path == "/api/users":
                status = 500
                payload = json.dumps({"error": "server_error", "message": "users unavailable"}).encode("utf-8")
                with lock:
                    requests_log.append({"method": method, "path": self.path, "status": status})
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if fail_post_users and method == "POST" and self.path == "/api/users":
                status = 500
                payload = json.dumps({"error": "create_failed", "message": "disk read-only"}).encode("utf-8")
                with lock:
                    requests_log.append({"method": method, "path": self.path, "status": status})
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            headers = {}
            if "content-type" in self.headers:
                headers["content-type"] = self.headers["content-type"]
            with lock:
                res = client.request(method, self.path, content=raw_body, headers=headers)
                requests_log.append({"method": method, "path": self.path, "status": res.status_code})
            body_bytes = res.content
            self.send_response(res.status_code)
            self.send_header("Content-Type", res.headers.get("content-type", "application/json"))
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}", requests_log
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _run_app_js(
    app,
    *,
    initial_storage: dict[str, str] | None = None,
    initial_hash: str = "#/",
    action: str | None = None,
    navigate_hash: str | None = None,
    fail_get_users: bool = False,
    fail_post_users: bool = False,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    node = shutil.which("node")
    assert node is not None, "node is required to exercise web/static/app.js"
    with _serve_test_app(
        app, fail_get_users=fail_get_users, fail_post_users=fail_post_users
    ) as (base_url, requests_log):
        cfg = {
            "appJsPath": str(APP_JS_PATH),
            "baseUrl": base_url,
            "initialStorage": initial_storage or {},
            "initialHash": initial_hash,
            "action": action,
            "navigateHash": navigate_hash,
        }
        proc = subprocess.run(
            [node, "-e", _NODE_HARNESS, json.dumps(cfg)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout), requests_log


@pytest.fixture
def web_bank(tmp_path):
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir(parents=True)
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True)

    # Asset fixture
    (assets_dir / "diagram.png").write_bytes(b"dummy png content")

    # Fixture questions
    q1 = {
        "id": "poscomp-2024-01",
        "exam": "poscomp",
        "year": 2024,
        "number": 1,
        "type": "mc",
        "status": "active",
        "stem": "What is SQL?",
        "options": ["A database language", "A browser", "An OS"],
        "answer": "A",
        "rubric": "Option A is the official definition.",
        "tags": ["databases", "sql"],
    }
    q2 = {
        "id": "poscomp-2024-02",
        "exam": "poscomp",
        "year": 2024,
        "number": 2,
        "type": "mc",
        "status": "suspended",
        "stem": "A suspended question about networks.",
        "options": ["LAN", "WAN"],
        "answer": "A",
        "tags": ["networks"],
    }
    q3 = {
        "id": "enade-2021-d1",
        "exam": "enade",
        "year": 2021,
        "number": 1,
        "type": "discursive",
        "status": "active",
        "stem": "Explain transaction isolation.",
        "answer": "Official explanation",
        "rubric": ["1 point for ACID", "2 points for isolation levels"],
        "tags": ["databases", "concurrency"],
    }
    for q in (q1, q2, q3):
        (questions_dir / f"{q['id']}.json").write_text(json.dumps(q), encoding="utf-8")

    # Topic registry (docs/tags.md). "concurrency" is deliberately unregistered.
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "tags.md").write_text(
        "# Tag Taxonomy\n\n"
        "## Registry (seeded)\n\n"
        "databases | Databases | area\n"
        "sql | SQL Language | subtopic\n"
        "networks | Networks | topic\n"
        "algebra-linear | Algebra Linear | topic\n"
        "\n## Aliases\n\n"
        "ignored-after-registry | Ignored | area\n",
        encoding="utf-8",
    )

    return tmp_path, (q1, q2, q3)


def test_users_endpoints_and_traversal_rejection(web_bank, monkeypatch):
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    root, _ = web_bank
    app = create_app(root)
    assert not (root / "data").exists()
    client = TestClient(app)

    # Initially empty users, default_user exposed without creating directories
    res = client.get("/api/users")
    assert res.status_code == 200
    assert res.json() == {"users": [], "default_user": "default"}
    assert not (root / "data").exists()

    # Honors QUESTION_BANK_USER without creating directories
    monkeypatch.setenv("QUESTION_BANK_USER", "legacy-user")
    res_configured = client.get("/api/users")
    assert res_configured.status_code == 200
    assert res_configured.json() == {"users": [], "default_user": "legacy-user"}
    assert not (root / "data").exists()

    # Invalid QUESTION_BANK_USER rejected rather than leaked
    monkeypatch.setenv("QUESTION_BANK_USER", "../escape")
    res_bad_env = client.get("/api/users")
    assert res_bad_env.status_code == 400
    assert res_bad_env.json()["error"] == "invalid_user"
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)

    # Create user
    res = client.post("/api/users", json={"name": "alice"})
    assert res.status_code == 201
    assert res.json() == {"name": "alice"}

    # Listed
    res = client.get("/api/users")
    assert res.status_code == 200
    assert res.json() == {"users": ["alice"], "default_user": "default"}

    # Reject traversal / invalid names on creation
    for bad in ("../escape", "Alice", "", "-bad", "a" * 33):
        res = client.post("/api/users", json={"name": bad})
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_user"

    # Reject traversal / invalid names in /api/u/{user}/ endpoints
    res = client.get("/api/u/../escape/stats")
    assert res.status_code in (400, 404)

    res = client.get("/api/u/UPPERCASE/stats")
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_user"

    # Unknown user returns 404
    res = client.get("/api/u/nonexistent/stats")
    assert res.status_code == 404
    assert res.json()["error"] == "user_not_found"


def test_web_ui_fresh_startup_creates_default_without_guessing_learner(web_bank, monkeypatch):
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    root, _ = web_bank
    legacy_log = root / "data" / "users" / "legacy-user" / "answers.jsonl"
    legacy_log.parent.mkdir(parents=True)
    legacy_bytes = b'{"id":"prior-1","is_correct":true,"tags":["databases"],"exam":"poscomp"}\n'
    legacy_log.write_bytes(legacy_bytes)

    app = create_app(root)
    assert not (root / "data" / "users" / "default").exists()

    ui, requests_log = _run_app_js(app, initial_storage={}, action="start_practice")

    assert [r["method"] + " " + r["path"] for r in requests_log[:2]] == [
        "GET /api/users",
        "POST /api/users",
    ]
    assert all(r["status"] < 400 for r in requests_log), requests_log
    assert ui["selectedUser"] == "default"
    assert ui["localStorage"] == {"qb_theme": "lamplight", "qb_user": "default", "qb_session_default": ui["localStorage"].get("qb_session_default")}
    assert [opt["value"] for opt in ui["userOptions"]] == ["default", "legacy-user", "__new__"]
    assert ui["alerts"] == []
    assert ui["hash"] == "#/practice"
    assert "1 /" in ui["appText"]
    assert (root / "data" / "users" / "default").is_dir()
    assert not (root / "data" / "users" / "default" / "answers.jsonl").exists()
    assert legacy_log.read_bytes() == legacy_bytes


def test_web_ui_configured_prior_username_selected(web_bank, monkeypatch):
    monkeypatch.setenv("QUESTION_BANK_USER", "legacy-user")
    root, (q1, _, _) = web_bank
    answers.record_answer(
        root,
        "legacy-user",
        {"question_id": q1["id"], "session_id": "prior", "given_answer": "A", "is_correct": True},
    )
    legacy_log = root / "data" / "users" / "legacy-user" / "answers.jsonl"
    legacy_bytes = legacy_log.read_bytes()

    ui, requests_log = _run_app_js(create_app(root), initial_storage={})

    assert all(r["status"] < 400 for r in requests_log), requests_log
    assert not any(r["method"] == "POST" and r["path"] == "/api/users" for r in requests_log)
    assert ui["selectedUser"] == "legacy-user"
    assert ui["localStorage"]["qb_user"] == "legacy-user"
    assert "1 answered - 100% correct" in ui["appText"]
    assert not (root / "data" / "users" / "default").exists()
    assert legacy_log.read_bytes() == legacy_bytes


def test_web_ui_valid_saved_choice_preserved_over_server_default(web_bank, monkeypatch):
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    root, (q1, _, _) = web_bank
    answers.create_user(root, "alice")
    answers.record_answer(
        root,
        "legacy-user",
        {"question_id": q1["id"], "session_id": "s1", "given_answer": "A", "is_correct": True},
    )
    app = create_app(root)
    assert TestClient(app).get("/api/users").json()["default_user"] == "default"

    ui, requests_log = _run_app_js(app, initial_storage={"qb_user": "legacy-user"})

    assert all(r["status"] < 400 for r in requests_log), requests_log
    assert not any(r["method"] == "POST" and r["path"] == "/api/users" for r in requests_log)
    assert ui["selectedUser"] == "legacy-user"
    assert ui["localStorage"]["qb_user"] == "legacy-user"
    assert "1 answered - 100% correct" in ui["appText"]
    assert not (root / "data" / "users" / "default").exists()


def test_web_ui_stale_saved_choice_falls_back_to_default(web_bank, monkeypatch):
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    root, _ = web_bank
    legacy_log = root / "data" / "users" / "legacy-user" / "answers.jsonl"
    legacy_log.parent.mkdir(parents=True)
    legacy_bytes = b'{"id":"prior-1","is_correct":false}\n'
    legacy_log.write_bytes(legacy_bytes)

    ui, requests_log = _run_app_js(
        create_app(root),
        initial_storage={"qb_user": "stale-profile"},
        action="start_practice",
    )

    assert [r["method"] + " " + r["path"] for r in requests_log[:2]] == [
        "GET /api/users",
        "POST /api/users",
    ]
    assert all(r["status"] < 400 for r in requests_log), requests_log
    assert ui["selectedUser"] == "default"
    assert ui["localStorage"]["qb_user"] == "default"
    assert [opt["value"] for opt in ui["userOptions"]] == ["default", "legacy-user", "__new__"]
    assert "stale-profile" not in [opt["value"] for opt in ui["userOptions"]]
    assert ui["hash"] == "#/practice"
    assert legacy_log.read_bytes() == legacy_bytes


def test_web_ui_failed_get_or_post_users_surfaces_failure(web_bank, monkeypatch):
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    root, _ = web_bank
    app = create_app(root)

    ui_get_fail, req_get_fail = _run_app_js(app, initial_storage={}, fail_get_users=True)
    assert [r["path"] for r in req_get_fail] == ["/api/users"]
    assert "qb_user" not in ui_get_fail["localStorage"]
    assert ui_get_fail["userOptions"] == []
    assert "Error" in ui_get_fail["appText"]
    assert "Start a session" not in ui_get_fail["appText"]

    ui_post_fail, req_post_fail = _run_app_js(
        app,
        initial_storage={"qb_user": "stale-profile"},
        initial_hash="#/stats",
        fail_post_users=True,
    )
    assert [(r["method"], r["path"]) for r in req_post_fail] == [
        ("GET", "/api/users"),
        ("POST", "/api/users"),
    ]
    assert ui_post_fail["localStorage"].get("qb_user") != "default"
    assert ui_post_fail["userOptions"] == []
    assert "Error" in ui_post_fail["appText"]
    assert "Statistics" not in ui_post_fail["appText"]


def test_question_endpoint_hides_answer(web_bank):
    root, (q1, _, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)

    # List questions
    res = client.get("/api/questions")
    assert res.status_code == 200
    data = res.json()
    # q2 is suspended, so default active only returns q1 and q3
    assert {q["id"] for q in data} == {q1["id"], q3["id"]}

    # With status=all
    res_all = client.get("/api/questions?status=all")
    assert res_all.status_code == 200
    assert len(res_all.json()) == 3

    # Filter by exam
    res_exam = client.get("/api/questions?exam=poscomp")
    assert res_exam.status_code == 200
    assert [q["id"] for q in res_exam.json()] == [q1["id"]]

    # Multiple-choice questions hide the answer and rubric
    res_q1 = client.get(f"/api/questions/{q1['id']}")
    assert res_q1.status_code == 200
    safe_q1 = res_q1.json()
    assert "answer" not in safe_q1
    assert "rubric" not in safe_q1
    assert safe_q1["stem"] == q1["stem"]

    res_q3 = client.get(f"/api/questions/{q3['id']}")
    assert res_q3.status_code == 200
    safe_q3 = res_q3.json()
    assert "answer" not in safe_q3
    assert safe_q3["rubric"] == q3["rubric"]

    # Traversal or nonexistent
    assert client.get("/api/questions/../nonexistent").status_code == 404
    assert client.get("/api/questions/missing-id").status_code == 404


def test_web_uses_live_corrections_for_questions_sessions_and_grading(web_bank):
    root, (q1, q2, q3) = web_bank
    client = TestClient(create_app(root))
    answers.create_user(root, "student")
    assert {q["id"] for q in client.get("/api/questions").json()} == {q1["id"], q3["id"]}

    log = root / "corrections" / "log.jsonl"
    log.parent.mkdir()
    qid = q1["id"]
    fixed_stem = "Which answer illustrates a relational query?"
    fixed_options = ["A browser", "A database language", "An OS"]
    entries = [
        (qid, "stem", fixed_stem),
        (qid, "options", fixed_options),
        (qid, "answer", "B"),
        (qid, "tags", ["sql"]),
        (q3["id"], "status", "suspended"),
    ]
    log.write_text(
        "".join(
            json.dumps({"question_id": question_id, "field": field, "new_value": value}) + "\n"
            for question_id, field, value in entries
        ),
        encoding="utf-8",
    )

    listed = client.get("/api/questions").json()
    assert [(q["id"], q["tags"]) for q in listed] == [(qid, ["sql"])]
    question = client.get(f"/api/questions/{qid}").json()
    assert question["stem"] == fixed_stem
    assert question["options"] == fixed_options

    session = client.post("/api/u/student/sessions", json={"count": 5}).json()
    assert session["question_ids"] == [qid]
    attempt = client.post(
        "/api/u/student/answer",
        json={"question_id": qid, "session_id": session["session_id"], "given_answer": "B"},
    ).json()
    assert attempt["is_correct"] is True
    assert attempt["correct_answer"] == "B"

    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"question_id": q2["id"], "field": "status", "new_value": "active"}) + "\n")
    assert {q["id"] for q in client.get("/api/questions").json()} == {qid, q2["id"]}

    log.unlink()
    assert {q["id"] for q in client.get("/api/questions").json()} == {qid, q3["id"]}


def test_session_creation(web_bank):
    root, (q1, q2, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)
    answers.create_user(root, "bob")

    # Session with active only
    res = client.post("/api/u/bob/sessions", json={"count": 5})
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert set(data["question_ids"]) == {q1["id"], q3["id"]}

    # Session including suspended
    res_susp = client.post("/api/u/bob/sessions", json={"count": 5, "include_suspended": True})
    assert res_susp.status_code == 200
    assert q2["id"] in res_susp.json()["question_ids"]

    # Session with tag filter
    res_tag = client.post("/api/u/bob/sessions", json={"tag": "concurrency"})
    assert res_tag.status_code == 200
    assert res_tag.json()["question_ids"] == [q3["id"]]


def test_answer_grading_correct_wrong_duplicate(web_bank):
    root, (q1, _, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)
    answers.create_user(root, "student")

    # Create session
    sess_res = client.post("/api/u/student/sessions", json={"count": 2})
    session_id = sess_res.json()["session_id"]

    # Multiple-choice correct
    ans_correct = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q1["id"],
            "session_id": session_id,
            "given_answer": "A",
            "time_spent": 10,
        },
    )
    assert ans_correct.status_code == 200
    body = ans_correct.json()
    assert body["is_correct"] is True
    assert body["correct_answer"] == "A"
    assert "record" in body
    assert body["record"]["time_spent"] == 10

    # Duplicate attempt in same session -> 409
    dup = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q1["id"],
            "session_id": session_id,
            "given_answer": "A",
        },
    )
    assert dup.status_code == 409
    assert dup.json()["error"] == "already_recorded"

    # New session: wrong answer
    ans_wrong = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q1["id"],
            "session_id": "sess-2",
            "given_answer": "C",
        },
    )
    assert ans_wrong.status_code == 200
    assert ans_wrong.json()["is_correct"] is False
    assert ans_wrong.json()["correct_answer"] == "A"

    # Discursive self-grading
    disc_correct = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q3["id"],
            "session_id": "sess-3",
            "given_answer": "Student essay",
            "self_grade": "correct",
        },
    )
    assert disc_correct.status_code == 200
    assert disc_correct.json()["is_correct"] is True
    assert disc_correct.json()["rubric"] == q3["rubric"]

    disc_partial = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q3["id"],
            "session_id": "sess-4",
            "given_answer": "Student essay",
            "self_grade": "partial",
        },
    )
    assert disc_partial.status_code == 200
    assert disc_partial.json()["is_correct"] is False

    # Resume session records
    sess1_records = client.get(f"/api/u/student/session/{session_id}")
    assert sess1_records.status_code == 200
    assert len(sess1_records.json()) == 1
    assert sess1_records.json()[0]["question_id"] == q1["id"]


def test_stats_ordering_and_activity(web_bank):
    root, (q1, _, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)
    answers.create_user(root, "statsuser")

    # student answers q1 (tags: databases, sql) correctly
    client.post(
        "/api/u/statsuser/answer",
        json={"question_id": q1["id"], "session_id": "s1", "given_answer": "A"},
    )
    # student answers q1 again in another session wrongly
    client.post(
        "/api/u/statsuser/answer",
        json={"question_id": q1["id"], "session_id": "s2", "given_answer": "B"},
    )
    # student answers q3 (tags: databases, concurrency) wrongly
    client.post(
        "/api/u/statsuser/answer",
        json={"question_id": q3["id"], "session_id": "s3", "given_answer": "essay", "self_grade": "wrong"},
    )

    res = client.get("/api/u/statsuser/stats")
    assert res.status_code == 200
    stats = res.json()

    assert stats["total"] == 3
    assert stats["correct"] == 1
    assert stats["accuracy"] == round(1 / 3, 4)

    # Stats group by topic (the second tag level), worst accuracy first.
    # concurrency: 0/1 = 0.0 accuracy
    # sql: 1/2 = 0.5 accuracy
    by_tag = stats["by_tag"]
    tags_in_order = [t["tag"] for t in by_tag]
    assert tags_in_order == ["concurrency", "sql"]

    # Check labels
    assert by_tag[0]["label"] == "Concurrency"
    assert by_tag[1]["label"] == "Sql"

    # Check activity array has 182 days
    activity = stats["activity"]
    assert len(activity) == 182
    assert activity[-1]["count"] == 3


def test_search_503_when_qdrant_unreachable(web_bank, monkeypatch):
    root, _ = web_bank
    app = create_app(root)
    client = TestClient(app)

    # Empty query returns empty list
    empty_res = client.get("/api/search?q=")
    assert empty_res.status_code == 200
    assert empty_res.json() == []

    # Search with qdrant unreachable returns 503
    res = client.get("/api/search?q=relational+databases")
    assert res.status_code == 503
    data = res.json()
    assert data["error"] == "search_unavailable"
    assert "message" in data


def test_security_headers_and_assets(web_bank):
    root, _ = web_bank
    app = create_app(root)
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"

    # Asset serving
    asset_res = client.get("/assets/diagram.png")
    assert asset_res.status_code == 200
    assert asset_res.content == b"dummy png content"

    # Asset traversal protection
    traversal_res = client.get("/assets/../../etc/passwd")
    assert traversal_res.status_code in (404, 400)


def _write_question(root, qid, year, tags, status="active"):
    q = {
        "id": qid, "exam": "poscomp", "year": year, "number": 1, "type": "mc",
        "status": status, "stem": "s", "options": ["a", "b"], "answer": "A", "tags": tags,
    }
    (root / "questions" / f"{qid}.json").write_text(json.dumps(q), encoding="utf-8")


def test_topics_shape_sort_and_registry_mapping(web_bank):
    root, _ = web_bank
    _write_question(root, "poscomp-2021-09", 2021, ["sql"])
    _write_question(root, "poscomp-2022-09", 2022, ["sql"])
    client = TestClient(create_app(root))

    res = client.get("/api/topics")
    assert res.status_code == 200
    body = res.json()
    topics = body["topics"]
    assert body["total"] == len(topics) == 4
    assert set(topics[0]) == {"slug", "name", "level", "active_questions", "by_year"}

    # sql: 3 active (q?: databases/sql from q1 + 2 new), databases: 2, ties by slug asc.
    assert [t["slug"] for t in topics] == ["sql", "databases", "algebra-linear", "networks"]
    by_slug = {t["slug"]: t for t in topics}
    assert by_slug["sql"]["name"] == "SQL Language"
    assert by_slug["sql"]["level"] == "subtopic"
    assert by_slug["databases"]["level"] == "area"
    assert by_slug["sql"]["active_questions"] == 3
    assert list(by_slug["sql"]["by_year"].items()) == [("2021", 1), ("2022", 1), ("2024", 1)]
    assert by_slug["databases"]["by_year"] == {"2021": 1, "2024": 1}


def test_topics_excludes_suspended_and_unregistered(web_bank):
    root, _ = web_bank
    client = TestClient(create_app(root))
    by_slug = {t["slug"]: t for t in client.get("/api/topics").json()["topics"]}

    # networks only has a suspended question: listed (registered) but zero count.
    assert by_slug["networks"]["active_questions"] == 0
    assert by_slug["networks"]["by_year"] == {}
    # concurrency is used by an active question but is not in the registry.
    assert "concurrency" not in by_slug
    # Rows after the Registry section are ignored.
    assert "ignored-after-registry" not in by_slug


def test_topics_level_and_limit_filters(web_bank):
    root, _ = web_bank
    client = TestClient(create_app(root))

    res = client.get("/api/topics", params={"level": "topic"})
    assert res.status_code == 200
    assert {t["level"] for t in res.json()["topics"]} == {"topic"}
    assert res.json()["total"] == 2

    res = client.get("/api/topics", params={"limit": 1})
    body = res.json()
    assert body["total"] == 4
    assert len(body["topics"]) == 1
    assert body["topics"][0]["slug"] == "databases"

    res = client.get("/api/topics", params={"level": "topic", "limit": 1})
    assert res.json()["total"] == 2
    assert len(res.json()["topics"]) == 1


def test_topics_invalid_params_and_missing_registry(web_bank):
    root, _ = web_bank
    client = TestClient(create_app(root))

    res = client.get("/api/topics", params={"level": "galaxy"})
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_level"}
    for bad in ("0", "501", "abc", "-3"):
        assert client.get("/api/topics", params={"limit": bad}).status_code == 400

    # Local bank docs/tags.md overrides bundled registry while present
    assert client.get("/api/topics").json()["total"] == 4

    # Removing local docs/tags.md falls back to resolve_tags(root) bundled registry
    _write_question(root, "poscomp-2024-99", 2024, ["banco-de-dados"])
    (root / "docs" / "tags.md").unlink()
    res = client.get("/api/topics", params={"limit": 500})
    assert res.status_code == 200
    body = res.json()
    bundled_text = bundled_tags().read_text(encoding="utf-8")
    assert "banco-de-dados | Banco De Dados | topic" in bundled_text
    assert body["total"] > 100
    assert body["topics"][0] == {
        "slug": "banco-de-dados",
        "name": "Banco De Dados",
        "level": "topic",
        "active_questions": 1,
        "by_year": {"2024": 1},
    }
