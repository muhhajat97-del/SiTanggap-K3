from __future__ import annotations

import csv
import io
import os
import re
import secrets
import socket
import sqlite3
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import (
    Flask, abort, g, jsonify, request, send_from_directory,
    session, make_response
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
STATUSES = {"Terbuka", "Dalam Proses", "Selesai"}
ROLES = {"admin", "hse", "pelapor"}

_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)


def now_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def risk_level(score: int) -> str:
    if score >= 15:
        return "Tinggi"
    if score >= 6:
        return "Sedang"
    return "Rendah"


def normalize_org_code(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]", "", raw.strip().lower())
    return cleaned


def generate_invite_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part1 = "".join(secrets.choice(alphabet) for _ in range(4))
    part2 = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"K3-{part1}-{part2}"


def _get_or_create_secret_key(instance_dir: Path) -> str:
    env_key = os.environ.get("SITANGGAP_SECRET_KEY", "").strip()
    if env_key and not env_key.startswith("ganti-dengan-"):
        return env_key
    instance_dir.mkdir(parents=True, exist_ok=True)
    key_file = instance_dir / ".secret_key"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if len(stored) >= 32:
            return stored
    generated = secrets.token_hex(32)
    key_file.write_text(generated, encoding="utf-8")
    return generated


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_rate_limit(bucket: str, max_attempts: int = 10, window_seconds: int = 300) -> bool:
    now = time.monotonic()
    key = f"{bucket}:{_client_ip()}"
    attempts = [t for t in _LOGIN_ATTEMPTS[key] if now - t < window_seconds]
    _LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) < max_attempts


def _record_attempt(bucket: str) -> None:
    _LOGIN_ATTEMPTS[f"{bucket}:{_client_ip()}"].append(time.monotonic())


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)  # type: ignore[method-assign]
    instance_path = BASE_DIR / "instance"
    cookie_secure_env = os.environ.get("SITANGGAP_COOKIE_SECURE", "auto").lower()
    app.config.from_mapping(
        SECRET_KEY=_get_or_create_secret_key(instance_path),
        DATABASE=os.environ.get("SITANGGAP_DATABASE", str(instance_path / "sitanggap_multitenant.db")),
        UPLOAD_FOLDER=os.environ.get("SITANGGAP_UPLOAD_FOLDER", str(instance_path / "uploads")),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.environ.get("SITANGGAP_COOKIE_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=(cookie_secure_env == "1"),
        COOKIE_SECURE_AUTO=(cookie_secure_env == "auto"),
        ALLOW_ORG_REGISTER=os.environ.get("SITANGGAP_ALLOW_ORG_REGISTER", "1") == "1",
        LOGIN_MAX_ATTEMPTS=int(os.environ.get("SITANGGAP_LOGIN_MAX_ATTEMPTS", "10")),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    def connect_db() -> sqlite3.Connection:
        connection = sqlite3.connect(app.config["DATABASE"], timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def init_db() -> None:
        db = connect_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                invite_code TEXT NOT NULL UNIQUE,
                allow_member_signup INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','hse','pelapor')),
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login TEXT,
                UNIQUE(organization_id, username)
            );
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                code TEXT,
                reporter TEXT NOT NULL,
                report_date TEXT NOT NULL,
                location TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                likelihood INTEGER NOT NULL CHECK(likelihood BETWEEN 1 AND 5),
                impact INTEGER NOT NULL CHECK(impact BETWEEN 1 AND 5),
                score INTEGER NOT NULL,
                level TEXT NOT NULL,
                assignee TEXT NOT NULL,
                due_date TEXT,
                corrective_action TEXT,
                status TEXT NOT NULL DEFAULT 'Terbuka' CHECK(status IN ('Terbuka','Dalam Proses','Selesai')),
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(organization_id, code)
            );
            CREATE TABLE IF NOT EXISTS report_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id),
                event TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                stored_name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                mimetype TEXT,
                size_bytes INTEGER NOT NULL,
                uploaded_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_users_org ON users(organization_id);
            CREATE INDEX IF NOT EXISTS idx_reports_org ON reports(organization_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_reports_org_creator ON reports(organization_id, created_by);
            CREATE INDEX IF NOT EXISTS idx_reports_org_status ON reports(organization_id, status);
            CREATE INDEX IF NOT EXISTS idx_reports_org_level ON reports(organization_id, level);
            CREATE INDEX IF NOT EXISTS idx_history_org_report ON report_history(organization_id, report_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_attachments_org ON attachments(organization_id, report_id);
            """
        )
        # Seed default demo organization if database is completely empty
        org_count = db.execute("SELECT COUNT(*) AS n FROM organizations").fetchone()["n"]
        if org_count == 0:
            bootstrap_password = os.environ.get("SITANGGAP_BOOTSTRAP_PASSWORD", "AdminK3Resmi2026!")
            now = now_local()
            cur = db.execute(
                """INSERT INTO organizations(org_code, name, invite_code, allow_member_signup, active, created_at)
                   VALUES(?, ?, ?, 1, 1, ?)""",
                ("demo-k3", "Instansi Demo SiTanggap K3", "K3-DEMO-2026", now),
            )
            org_id = cur.lastrowid
            db.execute(
                """INSERT INTO users(organization_id, username, full_name, role, password_hash, active,
                   must_change_password, created_at) VALUES(?,?,?,?,?,1,0,?)""",
                (org_id, "admin", "Administrator Demo K3", "admin",
                 generate_password_hash(bootstrap_password), now),
            )
            print("[SiTanggap K3] Workspace Demo dibuat:")
            print("  Kode Instansi : demo-k3 | Kode Undangan Anggota: K3-DEMO-2026")
            print("  Username Admin: admin   | Password: " + bootstrap_password)
        db.commit()
        db.close()

    app.extensions["sitanggap_connect_db"] = connect_db
    app.extensions["sitanggap_init_db"] = init_db
    init_db()

    def db_conn() -> sqlite3.Connection:
        if "db" not in g:
            g.db = connect_db()
        return g.db

    @app.teardown_appcontext
    def close_db(_error: Exception | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def current_user() -> sqlite3.Row | None:
        user_id = session.get("user_id")
        org_id = session.get("org_id")
        if not user_id or not org_id:
            return None
        return db_conn().execute(
            """SELECT u.id, u.organization_id, u.username, u.full_name, u.role, u.active, u.must_change_password,
                      o.org_code, o.name AS org_name, o.invite_code, o.allow_member_signup, o.active AS org_active
               FROM users u
               JOIN organizations o ON o.id = u.organization_id
               WHERE u.id=? AND u.organization_id=?""",
            (user_id, org_id),
        ).fetchone()

    def public_user(user: sqlite3.Row) -> dict[str, Any]:
        role_names = {"admin": "Administrator Instansi", "hse": "Petugas K3 / HSE", "pelapor": "Pelapor"}
        data = {
            "id": user["id"],
            "organization_id": user["organization_id"],
            "org_code": user["org_code"],
            "org_name": user["org_name"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "role_label": role_names.get(user["role"], user["role"]),
            "must_change_password": bool(user["must_change_password"]),
            "active": bool(user["active"]),
        }
        if user["role"] == "admin":
            data["invite_code"] = user["invite_code"]
            data["allow_member_signup"] = bool(user["allow_member_signup"])
        return data

    def login_required(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = current_user()
            if user is None or not user["active"] or not user["org_active"]:
                session.clear()
                return jsonify({"error": "Sesi berakhir atau akun tidak aktif. Silakan masuk kembali."}), 401
            g.current_user = user
            g.org_id = user["organization_id"]
            if user["must_change_password"] and request.endpoint not in {"me", "logout", "change_password"}:
                return jsonify({"error": "Kata sandi awal wajib diganti sebelum menggunakan aplikasi.", "must_change_password": True}), 428
            return fn(*args, **kwargs)
        return wrapper

    def roles_required(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(fn)
            @login_required
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if g.current_user["role"] not in roles:
                    return jsonify({"error": "Anda tidak memiliki hak akses untuk tindakan ini."}), 403
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    @app.before_request
    def csrf_protection() -> Any:
        if app.config.get("COOKIE_SECURE_AUTO"):
            app.config["SESSION_COOKIE_SECURE"] = request.is_secure
        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.endpoint in {"login", "register_org", "join_org"}:
                return None
            expected = session.get("csrf_token")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not secrets.compare_digest(expected, supplied):
                return jsonify({"error": "Token keamanan tidak valid. Muat ulang aplikasi dan coba kembali."}), 403
        return None

    @app.get("/")
    def index() -> Any:
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"status": "ok", "application": "SiTanggap K3 Multi-Instansi", "time": now_local()})

    @app.get("/api/public/config")
    def public_config() -> Any:
        return jsonify({
            "application": "SiTanggap K3",
            "allow_org_register": bool(app.config.get("ALLOW_ORG_REGISTER", True)),
        })

    @app.post("/api/auth/login", endpoint="login")
    def login() -> Any:
        max_attempts = int(app.config.get("LOGIN_MAX_ATTEMPTS", 10))
        if not _check_rate_limit("login", max_attempts=max_attempts, window_seconds=300):
            return jsonify({"error": "Terlalu banyak percobaan login gagal. Coba kembali dalam 5 menit."}), 429
        data = request.get_json(silent=True) or {}
        org_code = normalize_org_code(str(data.get("org_code", "")))
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", ""))
        if not org_code or not username or not password:
            return jsonify({"error": "Kode Instansi, Username, dan Kata Sandi wajib diisi."}), 400

        org = db_conn().execute("SELECT * FROM organizations WHERE org_code=?", (org_code,)).fetchone()
        if not org or not org["active"]:
            _record_attempt("login")
            return jsonify({"error": "Kode Instansi, username, atau kata sandi tidak sesuai."}), 401

        user = db_conn().execute(
            "SELECT * FROM users WHERE organization_id=? AND username=?",
            (org["id"], username),
        ).fetchone()
        if not user or not user["active"] or not check_password_hash(user["password_hash"], password):
            _record_attempt("login")
            return jsonify({"error": "Kode Instansi, username, atau kata sandi tidak sesuai."}), 401

        session.clear()
        session.permanent = True
        session["org_id"] = org["id"]
        session["user_id"] = user["id"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        db_conn().execute(
            "UPDATE users SET last_login=? WHERE id=? AND organization_id=?",
            (now_local(), user["id"], org["id"]),
        )
        db_conn().commit()
        fresh_user = current_user()
        return jsonify({"user": public_user(fresh_user), "csrf_token": session["csrf_token"]})

    @app.post("/api/auth/register-org", endpoint="register_org")
    def register_org() -> Any:
        if not app.config.get("ALLOW_ORG_REGISTER", True):
            return jsonify({"error": "Pendaftaran instansi baru saat ini ditutup."}), 403
        if not _check_rate_limit("register_org", max_attempts=5, window_seconds=600):
            return jsonify({"error": "Terlalu banyak percobaan pendaftaran. Silakan tunggu beberapa menit."}), 429

        data = request.get_json(silent=True) or {}
        org_name = str(data.get("org_name", "")).strip()
        org_code = normalize_org_code(str(data.get("org_code", "")))
        full_name = str(data.get("full_name", "")).strip()
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", ""))

        if len(org_name) < 3:
            return jsonify({"error": "Nama instansi/perusahaan minimal 3 karakter."}), 400
        if len(org_code) < 3 or len(org_code) > 32:
            return jsonify({"error": "Kode Instansi harus 3–32 karakter (huruf kecil, angka, tanda hubung - atau _)."}), 400
        if not username or not username.replace("_", "").replace(".", "").isalnum() or len(username) < 3:
            return jsonify({"error": "Username admin minimal 3 karakter (huruf, angka, titik, atau garis bawah)."}), 400
        if len(full_name) < 3:
            return jsonify({"error": "Nama lengkap admin minimal 3 karakter."}), 400
        if len(password) < 10:
            return jsonify({"error": "Kata sandi admin minimal 10 karakter."}), 400

        _record_attempt("register_org")
        now = now_local()
        invite_code = generate_invite_code()
        db = db_conn()
        try:
            cur_org = db.execute(
                """INSERT INTO organizations(org_code, name, invite_code, allow_member_signup, active, created_at)
                   VALUES(?, ?, ?, 1, 1, ?)""",
                (org_code, org_name, invite_code, now),
            )
            org_id = cur_org.lastrowid
            cur_user = db.execute(
                """INSERT INTO users(organization_id, username, full_name, role, password_hash, active,
                   must_change_password, created_at, last_login)
                   VALUES(?,?,?,?,?,1,0,?,?)""",
                (org_id, username, full_name, "admin", generate_password_hash(password), now, now),
            )
            user_id = cur_user.lastrowid
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify({"error": "Kode Instansi sudah digunakan oleh instansi lain. Silakan pilih kode unik lain."}), 409

        session.clear()
        session.permanent = True
        session["org_id"] = org_id
        session["user_id"] = user_id
        session["csrf_token"] = secrets.token_urlsafe(32)
        fresh_user = current_user()
        return jsonify({
            "message": f"Workspace instansi '{org_name}' berhasil dibuat.",
            "user": public_user(fresh_user),
            "csrf_token": session["csrf_token"],
        }), 201

    @app.post("/api/auth/join-org", endpoint="join_org")
    def join_org() -> Any:
        if not _check_rate_limit("join_org", max_attempts=8, window_seconds=600):
            return jsonify({"error": "Terlalu banyak percobaan pendaftaran. Silakan tunggu beberapa menit."}), 429

        data = request.get_json(silent=True) or {}
        invite_code = str(data.get("invite_code", "")).strip().upper()
        full_name = str(data.get("full_name", "")).strip()
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", ""))

        if not invite_code:
            return jsonify({"error": "Kode Undangan Instansi wajib diisi."}), 400
        if not username or not username.replace("_", "").replace(".", "").isalnum() or len(username) < 3:
            return jsonify({"error": "Username minimal 3 karakter (huruf, angka, titik, atau garis bawah)."}), 400
        if len(full_name) < 3:
            return jsonify({"error": "Nama lengkap minimal 3 karakter."}), 400
        if len(password) < 10:
            return jsonify({"error": "Kata sandi minimal 10 karakter."}), 400

        _record_attempt("join_org")
        db = db_conn()
        org = db.execute("SELECT * FROM organizations WHERE invite_code=?", (invite_code,)).fetchone()
        if not org or not org["active"]:
            return jsonify({"error": "Kode Undangan Instansi tidak ditemukan atau tidak aktif."}), 404
        if not org["allow_member_signup"]:
            return jsonify({"error": "Instansi ini menonaktifkan pendaftaran mandiri. Hubungi Administrator instansi Anda."}), 403

        now = now_local()
        try:
            cur_user = db.execute(
                """INSERT INTO users(organization_id, username, full_name, role, password_hash, active,
                   must_change_password, created_at, last_login)
                   VALUES(?,?,?,?,?,1,0,?,?)""",
                (org["id"], username, full_name, "pelapor", generate_password_hash(password), now, now),
            )
            user_id = cur_user.lastrowid
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "Username sudah digunakan di dalam instansi ini. Pilih username lain."}), 409

        session.clear()
        session.permanent = True
        session["org_id"] = org["id"]
        session["user_id"] = user_id
        session["csrf_token"] = secrets.token_urlsafe(32)
        fresh_user = current_user()
        return jsonify({
            "message": f"Berhasil bergabung ke {org['name']}.",
            "user": public_user(fresh_user),
            "csrf_token": session["csrf_token"],
        }), 201

    @app.get("/api/auth/me")
    @login_required
    def me() -> Any:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"user": public_user(g.current_user), "csrf_token": session["csrf_token"]})

    @app.post("/api/auth/logout")
    @login_required
    def logout() -> Any:
        session.clear()
        return jsonify({"message": "Anda telah keluar."})

    @app.post("/api/auth/change-password")
    @login_required
    def change_password() -> Any:
        data = request.get_json(silent=True) or {}
        current_password = str(data.get("current_password", ""))
        new_password = str(data.get("new_password", ""))
        row = db_conn().execute(
            "SELECT password_hash FROM users WHERE id=? AND organization_id=?",
            (g.current_user["id"], g.org_id),
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], current_password):
            return jsonify({"error": "Kata sandi saat ini tidak benar."}), 400
        if len(new_password) < 10:
            return jsonify({"error": "Kata sandi baru minimal 10 karakter."}), 400
        if new_password == current_password:
            return jsonify({"error": "Gunakan kata sandi yang berbeda."}), 400
        db_conn().execute(
            "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=? AND organization_id=?",
            (generate_password_hash(new_password), g.current_user["id"], g.org_id),
        )
        db_conn().commit()
        return jsonify({"message": "Kata sandi berhasil diubah."})

    # Organization settings (Admin only)
    @app.post("/api/organization/rotate-invite")
    @roles_required("admin")
    def rotate_invite_code() -> Any:
        new_code = generate_invite_code()
        db_conn().execute(
            "UPDATE organizations SET invite_code=? WHERE id=?",
            (new_code, g.org_id),
        )
        db_conn().commit()
        return jsonify({"invite_code": new_code, "message": "Kode undangan instansi berhasil diperbarui."})

    @app.patch("/api/organization")
    @roles_required("admin")
    def update_organization() -> Any:
        data = request.get_json(silent=True) or {}
        org = db_conn().execute("SELECT * FROM organizations WHERE id=?", (g.org_id,)).fetchone()
        name = str(data.get("name", org["name"])).strip()
        allow_signup = bool(data.get("allow_member_signup", org["allow_member_signup"]))
        if len(name) < 3:
            return jsonify({"error": "Nama instansi minimal 3 karakter."}), 400
        db_conn().execute(
            "UPDATE organizations SET name=?, allow_member_signup=? WHERE id=?",
            (name, int(allow_signup), g.org_id),
        )
        db_conn().commit()
        return jsonify({"message": "Pengaturan instansi berhasil diperbarui.", "name": name, "allow_member_signup": allow_signup})

    def can_access_report(report: sqlite3.Row) -> bool:
        if report["organization_id"] != g.org_id:
            return False
        return g.current_user["role"] in {"admin", "hse"} or report["created_by"] == g.current_user["id"]

    def report_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def add_history(report_id: int, user_id: int | None, event: str, note: str | None = None) -> None:
        db_conn().execute(
            "INSERT INTO report_history(organization_id,report_id,user_id,event,note,created_at) VALUES(?,?,?,?,?,?)",
            (g.org_id, report_id, user_id, event, note or "", now_local()),
        )

    def get_report(report_id: int) -> sqlite3.Row | None:
        return db_conn().execute(
            """SELECT r.*, u.full_name AS creator_name FROM reports r
               JOIN users u ON u.id=r.created_by
               WHERE r.id=? AND r.organization_id=?""",
            (report_id, g.org_id),
        ).fetchone()

    def report_filters(base_sql: str, params: list[Any]) -> tuple[str, list[Any]]:
        q = request.args.get("q", "").strip()
        risk = request.args.get("risk", "all")
        status = request.args.get("status", "all")
        if q:
            base_sql += " AND (r.code LIKE ? OR r.title LIKE ? OR r.location LIKE ? OR r.category LIKE ?)"
            params.extend([f"%{q}%"] * 4)
        if risk in {"Tinggi", "Sedang", "Rendah"}:
            base_sql += " AND r.level=?"
            params.append(risk)
        if status in STATUSES:
            base_sql += " AND r.status=?"
            params.append(status)
        return base_sql, params

    @app.get("/api/dashboard")
    @login_required
    def dashboard() -> Any:
        params: list[Any] = [g.org_id]
        base = "SELECT r.* FROM reports r WHERE r.organization_id=?"
        if g.current_user["role"] == "pelapor":
            base += " AND r.created_by=?"
            params.append(g.current_user["id"])
        rows = db_conn().execute(base, params).fetchall()
        total = len(rows)
        high = sum(1 for r in rows if r["level"] == "Tinggi")
        progress = sum(1 for r in rows if r["status"] == "Dalam Proses")
        done = sum(1 for r in rows if r["status"] == "Selesai")
        distribution = {level: sum(1 for r in rows if r["level"] == level) for level in ["Tinggi", "Sedang", "Rendah"]}
        ordered = sorted(rows, key=lambda r: r["created_at"], reverse=True)
        priority = sorted([r for r in rows if r["status"] != "Selesai"], key=lambda r: (r["score"], r["created_at"]), reverse=True)
        return jsonify({
            "total": total, "high": high, "progress": progress, "done": done,
            "distribution": distribution,
            "recent": [report_dict(r) for r in ordered[:5]],
            "priority": [report_dict(r) for r in priority[:8]],
        })

    @app.get("/api/reports")
    @login_required
    def list_reports() -> Any:
        sql = "SELECT r.* FROM reports r WHERE r.organization_id=?"
        params: list[Any] = [g.org_id]
        if g.current_user["role"] == "pelapor":
            sql += " AND r.created_by=?"
            params.append(g.current_user["id"])
        sql, params = report_filters(sql, params)
        sql += " ORDER BY r.created_at DESC"
        rows = db_conn().execute(sql, params).fetchall()
        return jsonify({"items": [report_dict(r) for r in rows], "count": len(rows)})

    @app.post("/api/reports")
    @login_required
    def create_report() -> Any:
        data = request.form if request.content_type and request.content_type.startswith("multipart/form-data") else (request.get_json(silent=True) or {})
        required = ["reporter", "report_date", "location", "category", "title", "description", "likelihood", "impact", "assignee"]
        missing = [key for key in required if not str(data.get(key, "")).strip()]
        if missing:
            return jsonify({"error": "Lengkapi kolom wajib: " + ", ".join(missing)}), 400
        try:
            likelihood = int(data.get("likelihood"))
            impact = int(data.get("impact"))
        except (TypeError, ValueError):
            return jsonify({"error": "Nilai kemungkinan dan dampak harus berupa angka 1–5."}), 400
        if not (1 <= likelihood <= 5 and 1 <= impact <= 5):
            return jsonify({"error": "Nilai kemungkinan dan dampak harus berada pada rentang 1–5."}), 400
        score = likelihood * impact
        level = risk_level(score)
        timestamp = now_local()

        # Sequence number isolated per organization
        org_seq = db_conn().execute(
            "SELECT COUNT(*) AS n FROM reports WHERE organization_id=?",
            (g.org_id,),
        ).fetchone()["n"] + 1

        cursor = db_conn().execute(
            """INSERT INTO reports(organization_id,reporter,report_date,location,category,title,description,
               likelihood,impact,score,level,assignee,due_date,corrective_action,status,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'Terbuka',?,?,?)""",
            (g.org_id, str(data["reporter"]).strip(), str(data["report_date"]).strip(), str(data["location"]).strip(),
             str(data["category"]).strip(), str(data["title"]).strip(), str(data["description"]).strip(),
             likelihood, impact, score, level, str(data["assignee"]).strip(),
             str(data.get("due_date", "")).strip(), str(data.get("corrective_action", "")).strip(),
             g.current_user["id"], timestamp, timestamp),
        )
        report_id = cursor.lastrowid
        code = f"STK3-{datetime.now():%Y%m}-{org_seq:04d}"
        db_conn().execute("UPDATE reports SET code=? WHERE id=? AND organization_id=?", (code, report_id, g.org_id))
        add_history(report_id, g.current_user["id"], "Laporan dibuat", f"Laporan dicatat oleh {g.current_user['full_name']}. Skor risiko: {score} ({level}).")

        photo = request.files.get("photo") if request.files else None
        if photo and photo.filename:
            original = secure_filename(photo.filename)
            ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                db_conn().rollback()
                return jsonify({"error": "Format foto harus PNG, JPG, JPEG, atau WEBP."}), 400
            photo.stream.seek(0, os.SEEK_END)
            size = photo.stream.tell()
            photo.stream.seek(0)
            if size > MAX_UPLOAD_BYTES:
                db_conn().rollback()
                return jsonify({"error": "Ukuran foto maksimum 5 MB."}), 400
            signature = photo.stream.read(12)
            photo.stream.seek(0)
            is_png = signature.startswith(bytes.fromhex("89504e470d0a1a0a"))
            is_jpeg = signature.startswith(bytes.fromhex("ffd8ff"))
            is_webp = signature.startswith(b"RIFF") and signature[8:12] == b"WEBP"
            extension_matches = ((ext == "png" and is_png) or
                                 (ext in {"jpg", "jpeg"} and is_jpeg) or
                                 (ext == "webp" and is_webp))
            if not extension_matches:
                db_conn().rollback()
                return jsonify({"error": "Isi berkas tidak sesuai dengan ekstensi gambar PNG, JPG, JPEG, atau WEBP."}), 400

            # Isolate uploaded files physically per organization folder
            org_upload_dir = Path(app.config["UPLOAD_FOLDER"]) / f"org_{g.org_id}"
            org_upload_dir.mkdir(parents=True, exist_ok=True)
            stored = f"{uuid.uuid4().hex}.{ext}"
            photo.save(org_upload_dir / stored)
            db_conn().execute(
                "INSERT INTO attachments(organization_id,report_id,stored_name,original_name,mimetype,size_bytes,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (g.org_id, report_id, stored, original, photo.mimetype, size, g.current_user["id"], timestamp),
            )
        db_conn().commit()
        return jsonify({"message": "Laporan berhasil disimpan.", "id": report_id, "code": code, "score": score, "level": level}), 201

    @app.get("/api/reports/<int:report_id>")
    @login_required
    def report_detail(report_id: int) -> Any:
        report = get_report(report_id)
        if not report:
            return jsonify({"error": "Laporan tidak ditemukan."}), 404
        if not can_access_report(report):
            return jsonify({"error": "Anda tidak dapat mengakses laporan ini."}), 403
        history = db_conn().execute(
            """SELECT h.id,h.event,h.note,h.created_at,u.full_name AS actor
               FROM report_history h LEFT JOIN users u ON u.id=h.user_id
               WHERE h.report_id=? AND h.organization_id=? ORDER BY h.created_at DESC,h.id DESC""",
            (report_id, g.org_id),
        ).fetchall()
        attachments = db_conn().execute(
            "SELECT id,original_name,mimetype,size_bytes,created_at FROM attachments WHERE report_id=? AND organization_id=? ORDER BY id DESC",
            (report_id, g.org_id),
        ).fetchall()
        result = report_dict(report)
        result["history"] = [dict(h) for h in history]
        result["attachments"] = [dict(a, url=f"/api/attachments/{a['id']}") for a in attachments]
        return jsonify(result)

    @app.patch("/api/reports/<int:report_id>")
    @roles_required("admin", "hse")
    def update_report(report_id: int) -> Any:
        report = get_report(report_id)
        if not report:
            return jsonify({"error": "Laporan tidak ditemukan."}), 404
        data = request.get_json(silent=True) or {}
        status = str(data.get("status", report["status"]))
        if status not in STATUSES:
            return jsonify({"error": "Status tidak dikenal."}), 400
        assignee = str(data.get("assignee", report["assignee"])).strip()
        due_date = str(data.get("due_date", report["due_date"] or "")).strip()
        action = str(data.get("corrective_action", report["corrective_action"] or "")).strip()
        note = str(data.get("note", "")).strip()
        if status == "Selesai" and not (action or note):
            return jsonify({"error": "Catatan tindakan koreksi atau catatan penyelesaian wajib diisi sebelum laporan ditutup."}), 400
        if not assignee:
            return jsonify({"error": "Penanggung jawab tidak boleh kosong."}), 400
        changed = []
        if status != report["status"]:
            changed.append(f"Status: {report['status']} → {status}")
        if assignee != report["assignee"]:
            changed.append(f"Penanggung jawab: {report['assignee']} → {assignee}")
        if due_date != (report["due_date"] or ""):
            changed.append("Target penyelesaian diperbarui")
        if action != (report["corrective_action"] or ""):
            changed.append("Tindakan koreksi diperbarui")
        if note:
            changed.append(note)
        if not changed:
            return jsonify({"message": "Tidak ada perubahan yang disimpan."})
        db_conn().execute(
            "UPDATE reports SET status=?,assignee=?,due_date=?,corrective_action=?,updated_at=? WHERE id=? AND organization_id=?",
            (status, assignee, due_date, action, now_local(), report_id, g.org_id),
        )
        add_history(report_id, g.current_user["id"], "Pembaruan tindak lanjut", "; ".join(changed))
        db_conn().commit()
        return jsonify({"message": "Pembaruan laporan berhasil disimpan."})

    @app.post("/api/reports/<int:report_id>/comments")
    @login_required
    def add_comment(report_id: int) -> Any:
        report = get_report(report_id)
        if not report:
            return jsonify({"error": "Laporan tidak ditemukan."}), 404
        if not can_access_report(report):
            return jsonify({"error": "Anda tidak dapat mengakses laporan ini."}), 403
        data = request.get_json(silent=True) or {}
        note = str(data.get("note", "")).strip()
        if not note:
            return jsonify({"error": "Catatan tidak boleh kosong."}), 400
        add_history(report_id, g.current_user["id"], "Catatan", note[:2000])
        db_conn().commit()
        return jsonify({"message": "Catatan berhasil ditambahkan."}), 201

    @app.get("/api/attachments/<int:attachment_id>")
    @login_required
    def get_attachment(attachment_id: int) -> Any:
        row = db_conn().execute(
            """SELECT a.*, r.created_by FROM attachments a
               JOIN reports r ON r.id=a.report_id AND r.organization_id=a.organization_id
               WHERE a.id=? AND a.organization_id=?""",
            (attachment_id, g.org_id),
        ).fetchone()
        if not row:
            abort(404)
        if g.current_user["role"] not in {"admin", "hse"} and row["created_by"] != g.current_user["id"]:
            abort(403)
        org_upload_dir = Path(app.config["UPLOAD_FOLDER"]) / f"org_{g.org_id}"
        if (org_upload_dir / row["stored_name"]).exists():
            return send_from_directory(org_upload_dir, row["stored_name"],
                                       as_attachment=False, download_name=row["original_name"])
        return send_from_directory(app.config["UPLOAD_FOLDER"], row["stored_name"],
                                   as_attachment=False, download_name=row["original_name"])

    @app.get("/api/reports/export.csv")
    @login_required
    def export_reports() -> Any:
        sql = """SELECT r.code,r.reporter,r.report_date,r.location,r.category,r.title,r.description,
                        r.likelihood,r.impact,r.score,r.level,r.assignee,r.due_date,r.corrective_action,
                        r.status,r.created_at,r.updated_at
                 FROM reports r WHERE r.organization_id=?"""
        params: list[Any] = [g.org_id]
        if g.current_user["role"] == "pelapor":
            sql += " AND r.created_by=?"
            params.append(g.current_user["id"])
        sql, params = report_filters(sql, params)
        sql += " ORDER BY r.created_at DESC"
        rows = db_conn().execute(sql, params).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["ID Laporan", "Pelapor", "Tanggal", "Lokasi", "Kategori", "Judul", "Uraian", "Kemungkinan", "Dampak", "Skor", "Tingkat Risiko", "Penanggung Jawab", "Target", "Tindakan Koreksi", "Status", "Dibuat", "Diperbarui"])
        for row in rows:
            writer.writerow([row[k] for k in row.keys()])
        response = make_response("﻿" + output.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        safe_org = secure_filename(g.current_user["org_code"]) or "instansi"
        response.headers["Content-Disposition"] = f"attachment; filename=sitanggap_k3_{safe_org}_laporan.csv"
        return response

    @app.get("/api/users")
    @roles_required("admin")
    def list_users() -> Any:
        rows = db_conn().execute(
            """SELECT id,username,full_name,role,active,must_change_password,created_at,last_login
               FROM users WHERE organization_id=? ORDER BY created_at DESC""",
            (g.org_id,),
        ).fetchall()
        return jsonify({"items": [dict(r) for r in rows]})

    @app.post("/api/users")
    @roles_required("admin")
    def create_user() -> Any:
        data = request.get_json(silent=True) or {}
        username = str(data.get("username", "")).strip().lower()
        full_name = str(data.get("full_name", "")).strip()
        role = str(data.get("role", "")).strip()
        password = str(data.get("password", ""))
        if not username or not username.replace("_", "").replace(".", "").isalnum():
            return jsonify({"error": "Username hanya boleh berisi huruf, angka, titik, dan garis bawah."}), 400
        if len(username) < 3 or len(full_name) < 3:
            return jsonify({"error": "Username dan nama minimal 3 karakter."}), 400
        if role not in {"admin", "hse", "pelapor"}:
            return jsonify({"error": "Peran tidak valid."}), 400
        if len(password) < 10:
            return jsonify({"error": "Kata sandi awal minimal 10 karakter."}), 400
        try:
            db_conn().execute(
                """INSERT INTO users(organization_id,username,full_name,role,password_hash,active,must_change_password,created_at)
                   VALUES(?,?,?,?,?,1,1,?)""",
                (g.org_id, username, full_name, role, generate_password_hash(password), now_local()),
            )
            db_conn().commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "Username sudah digunakan di instansi ini."}), 409
        return jsonify({"message": "Akun berhasil dibuat. Pengguna wajib mengganti kata sandi saat login pertama."}), 201

    @app.patch("/api/users/<int:user_id>")
    @roles_required("admin")
    def update_user(user_id: int) -> Any:
        row = db_conn().execute(
            "SELECT * FROM users WHERE id=? AND organization_id=?",
            (user_id, g.org_id),
        ).fetchone()
        if not row:
            return jsonify({"error": "Pengguna tidak ditemukan pada instansi ini."}), 404
        data = request.get_json(silent=True) or {}
        active = bool(data.get("active", row["active"]))
        full_name = str(data.get("full_name", row["full_name"])).strip()
        role = str(data.get("role", row["role"])).strip()
        if role not in ROLES:
            return jsonify({"error": "Peran tidak valid."}), 400
        if user_id == g.current_user["id"] and (not active or role != "admin"):
            return jsonify({"error": "Akun admin yang sedang digunakan tidak dapat dinonaktifkan atau diturunkan perannya."}), 400
        if not full_name:
            return jsonify({"error": "Nama pengguna tidak boleh kosong."}), 400
        db_conn().execute(
            "UPDATE users SET active=?,full_name=?,role=? WHERE id=? AND organization_id=?",
            (int(active), full_name, role, user_id, g.org_id),
        )
        db_conn().commit()
        return jsonify({"message": "Data pengguna diperbarui."})

    @app.after_request
    def security_headers(response: Any) -> Any:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        return response

    @app.errorhandler(413)
    def file_too_large(_error: Any) -> Any:
        return jsonify({"error": "Ukuran unggahan melebihi batas 5 MB."}), 413

    @app.errorhandler(404)
    def not_found(_error: Any) -> Any:
        if request.path.startswith("/api/"):
            return jsonify({"error": "Data atau alamat tidak ditemukan."}), 404
        return "Halaman tidak ditemukan", 404

    @app.errorhandler(403)
    def forbidden(_error: Any) -> Any:
        if request.path.startswith("/api/"):
            return jsonify({"error": "Akses ditolak."}), 403
        return "Akses ditolak", 403

    return app


app = create_app()


def get_local_ips() -> list[str]:
    ips = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


if __name__ == "__main__":
    host = os.environ.get("SITANGGAP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT") or os.environ.get("SITANGGAP_PORT", "5000"))
    debug = os.environ.get("SITANGGAP_DEBUG", "0") == "1"

    print("=" * 65)
    print("SiTanggap K3 Multi-Instansi — Server Siap Digunakan")
    print(f"Akses Lokal    : http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        for ip in get_local_ips():
            print(f"Akses Jaringan : http://{ip}:{port}")
    print("=" * 65)

    if debug:
        app.run(host=host, port=port, debug=True)
    else:
        try:
            from waitress import serve
            serve(app, host=host, port=port, threads=8)
        except ImportError:
            app.run(host=host, port=port, debug=False)
