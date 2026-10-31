import json
import mimetypes
import os
import re
import socket
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Any, Optional

import psutil

from .database import Database, clean_api_key
from .gemini_service import GeminiService, FALLBACK_MODELS

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

db = Database()
gemini_service = GeminiService()

# Track active generation cancellation tokens per session_id
active_generations: Dict[str, bool] = {}
generations_lock = threading.Lock()


def set_cancelled(session_id: str, value: bool = True):
    with generations_lock:
        active_generations[session_id] = value


def is_cancelled(session_id: str) -> bool:
    with generations_lock:
        return active_generations.get(session_id, False)


def get_system_telemetry() -> Dict[str, Any]:
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        return {
            "cpu_percent": round(cpu, 1),
            "ram_percent": round(mem.percent, 1),
            "ram_used_gb": round(mem.used / (1024 ** 3), 2),
            "ram_total_gb": round(mem.total / (1024 ** 3), 2),
            "timestamp": time.time(),
        }
    except Exception:
        return {
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "timestamp": time.time(),
        }


class GemOSRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args):
        # Quiet clean logging
        pass

    def _send_json(self, data: Any, status: int = 200):
        self.close_connection = True
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self):
        self.close_connection = True
        self.send_response(204)
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/api/health":
                return self._send_json({"status": "online", "version": "4.2.0-CTOS"})

            if path == "/api/telemetry":
                return self._send_json(get_system_telemetry())

            if path == "/api/settings":
                settings = db.get_all_settings()
                force_refresh = query.get("refresh", ["0"])[0] == "1"
                api_key = db.get_setting("api_key")
                live_models = gemini_service.list_available_models(api_key, force_refresh=force_refresh)
                settings["available_models"] = live_models
                return self._send_json(settings)

            if path == "/api/models":
                force_refresh = query.get("refresh", ["0"])[0] == "1"
                api_key = db.get_setting("api_key")
                live_models = gemini_service.list_available_models(api_key, force_refresh=force_refresh)
                return self._send_json({"models": live_models})

            if path == "/api/sessions":
                q = query.get("q", [""])[0]
                sessions = db.list_sessions(q)
                return self._send_json({"sessions": sessions})

            m = re.match(r"^/api/sessions/([^/]+)$", path)
            if m:
                session_id = m.group(1)
                session = db.get_session(session_id)
                if not session:
                    return self._send_json({"error": "Session not found"}, 404)
                return self._send_json(session)

            m_export = re.match(r"^/api/sessions/([^/]+)/export$", path)
            if m_export:
                session_id = m_export.group(1)
                fmt = query.get("format", ["markdown"])[0]
                session = db.get_session(session_id)
                if not session:
                    return self._send_json({"error": "Session not found"}, 404)
                if fmt == "json":
                    return self._send_json(session)
                else:
                    md_lines = [
                        f"# {session['title']}",
                        f"*Model: `{session['model']}` | Exported from GemOS CTos v4.2*",
                        "",
                        "---",
                        "",
                    ]
                    for msg in session.get("messages", []):
                        role_label = "USER" if msg["role"] == "user" else "GEMINI"
                        md_lines.append(f"### [{role_label}]")
                        for att in msg.get("attachments", []):
                            md_lines.append(f"> Attached: `{att.get('filename', 'file')}`")
                        md_lines.append(msg["content"])
                        md_lines.append("")
                    return self._send_json(
                        {
                            "filename": f"{re.sub(r'[^a-zA-Z0-9_-]', '_', session['title'])}.md",
                            "content": "\n".join(md_lines),
                        }
                    )

            # Static files
            return self._serve_static(path)
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/settings":
                body = self._read_json()
                if "api_key" in body and body["api_key"] is not None:
                    cleaned = clean_api_key(body["api_key"])
                    if cleaned:
                        db.set_setting("api_key", cleaned)
                for key in ("model", "theme", "system_instruction", "temperature", "top_p", "max_output_tokens"):
                    if key in body and body[key] is not None:
                        db.set_setting(key, str(body[key]))
                settings = db.get_all_settings()
                settings["available_models"] = gemini_service.list_available_models(db.get_setting("api_key"))
                return self._send_json(settings)

            if path == "/api/settings/validate-key":
                body = self._read_json()
                raw_key = body.get("api_key", "")
                key = clean_api_key(raw_key) if raw_key else db.get_setting("api_key")
                if not key:
                    return self._send_json({"valid": False, "error": "No API key provided."}, 400)
                res = gemini_service.validate_key(key)
                if res.get("valid") and raw_key:
                    db.set_setting("api_key", key)
                return self._send_json(res)

            if path == "/api/sessions":
                body = self._read_json()
                session = db.create_session(
                    title=body.get("title", "New Operation"),
                    model=body.get("model"),
                    system_instruction=body.get("system_instruction"),
                    persona_id=body.get("persona_id", "default"),
                    temperature=body.get("temperature"),
                    top_p=body.get("top_p"),
                    max_output_tokens=body.get("max_output_tokens"),
                )
                return self._send_json(session, 201)

            m_clear = re.match(r"^/api/sessions/([^/]+)/clear$", path)
            if m_clear:
                session_id = m_clear.group(1)
                session = db.clear_session_messages(session_id)
                return self._send_json(session)

            m_cancel = re.match(r"^/api/sessions/([^/]+)/cancel$", path)
            if m_cancel:
                session_id = m_cancel.group(1)
                set_cancelled(session_id, True)
                return self._send_json({"cancelled": True})

            m_stream = re.match(r"^/api/sessions/([^/]+)/stream$", path)
            if m_stream:
                session_id = m_stream.group(1)
                body = self._read_json()
                return self._handle_chat_stream(session_id, body)

            return self._send_json({"error": "Not found"}, 404)
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            m = re.match(r"^/api/sessions/([^/]+)$", path)
            if m:
                session_id = m.group(1)
                body = self._read_json()
                updated = db.update_session(session_id, **body)
                if not updated:
                    return self._send_json({"error": "Session not found"}, 404)
                return self._send_json(updated)
            return self._send_json({"error": "Not found"}, 404)
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            m = re.match(r"^/api/sessions/([^/]+)$", path)
            if m:
                session_id = m.group(1)
                ok = db.delete_session(session_id)
                return self._send_json({"deleted": ok})

            m_msg = re.match(r"^/api/sessions/([^/]+)/messages/([^/]+)$", path)
            if m_msg:
                session_id, message_id = m_msg.group(1), m_msg.group(2)
                ok = db.delete_messages_from(session_id, message_id)
                return self._send_json({"deleted": ok, "session": db.get_session(session_id)})

            return self._send_json({"error": "Not found"}, 404)
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def _handle_chat_stream(self, session_id: str, body: Dict[str, Any]):
        session = db.get_session(session_id)
        if not session:
            return self._send_json({"error": "Session not found"}, 404)

        user_text = body.get("content", "").strip()
        attachments = body.get("attachments", [])
        regenerate_from_id = body.get("regenerate_from_id")

        if regenerate_from_id:
            db.delete_messages_from(session_id, regenerate_from_id)
            session = db.get_session(session_id)

        history = session.get("messages", [])

        # Save user message unless this is a pure regeneration of an existing last user message
        if not body.get("skip_user_save"):
            shown_text = user_text if user_text else "Please analyze the attached file(s)."
            user_msg = db.add_message(
                session_id=session_id,
                role="user",
                content=shown_text,
                attachments=attachments,
            )
            # Auto-title if session is still "New Operation" and this is the first message
            if len(history) == 0 and session["title"] in ("New Operation", "New Chat"):
                auto_title = self._generate_smart_title(user_text, attachments)
                db.update_session(session_id, title=auto_title)
                session["title"] = auto_title
        else:
            user_msg = history[-1] if history else None
            if user_msg and user_msg["role"] == "user":
                user_text = user_msg["content"]
                attachments = user_msg.get("attachments", [])
                history = history[:-1]

        api_key = db.get_setting("api_key")
        set_cancelled(session_id, False)

        # Send SSE headers and ensure connection closes when stream ends so client reader.read() never hangs
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def send_sse(event_data: Dict[str, Any]):
            line = f"data: {json.dumps(event_data)}\n\n".encode("utf-8")
            self.wfile.write(line)
            self.wfile.flush()

        try:
            send_sse(
                {
                    "type": "start",
                    "user_message": user_msg,
                    "session_title": session["title"],
                }
            )

            model_to_use = body.get("model") or session["model"]
            final_text = ""
            final_images = []
            final_meta: Dict[str, Any] = {}

            for event in gemini_service.stream_chat(
                api_key=api_key,
                model=model_to_use,
                system_instruction=session["system_instruction"],
                temperature=float(session.get("temperature", 0.7)),
                top_p=float(session.get("top_p", 0.95)),
                max_output_tokens=int(session.get("max_output_tokens", 8192)),
                history=history,
                user_text=user_text,
                attachments=attachments,
                cancel_Check=lambda: is_cancelled(session_id),
            ):
                if event["type"] == "delta":
                    final_text += event["delta"]
                    send_sse(event)
                elif event["type"] == "image":
                    final_images.append(event["image"])
                    send_sse(event)
                elif event["type"] == "cancelled":
                    final_text = event.get("full_text", final_text)
                    final_images = event.get("generated_images", final_images)
                    final_meta = {
                        "cancelled": True,
                        "elapsed_ms": event.get("elapsed_ms", 0),
                        "model": event.get("model", model_to_use),
                    }
                    saved_msg = db.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=final_text + "\n\n*[Generation aborted]*",
                        attachments=final_images,
                        metadata=final_meta,
                    )
                    wire_msg = {**saved_msg, "attachments": [{k: v for k, v in a.items() if k != "data_base64"} for a in final_images]}
                    send_sse({"type": "cancelled", "assistant_message": wire_msg})
                    return
                elif event["type"] == "error":
                    err_text = event.get("error", "Unknown error")
                    send_sse({"type": "error", "error": err_text})
                    return
                elif event["type"] == "done":
                    final_text = event.get("full_text", final_text)
                    final_images = event.get("generated_images", final_images)
                    final_meta = {
                        "elapsed_ms": event.get("elapsed_ms", 0),
                        "ttft_ms": event.get("ttft_ms", 0),
                        "usage": event.get("usage", {}),
                        "model": event.get("model", model_to_use),
                    }
                    saved_msg = db.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=final_text,
                        attachments=final_images,
                        metadata=final_meta,
                    )
                    # Avoid sending multi-MB base64 images a second time over SSE in 'done'
                    wire_msg = {**saved_msg, "attachments": [{k: v for k, v in a.items() if k != "data_base64"} for a in final_images]}
                    send_sse(
                        {
                            "type": "done",
                            "assistant_message": wire_msg,
                            "session_title": session["title"],
                        }
                    )
                    return
        except (BrokenPipeError, ConnectionResetError):
            set_cancelled(session_id, True)
        except Exception as e:
            try:
                send_sse({"type": "error", "error": str(e)})
            except Exception:
                pass

    def _generate_smart_title(self, user_text: str, attachments: list) -> str:
        if user_text:
            cleaned = re.sub(r"\s+", " ", user_text).strip()
            cleaned = re.sub(r"^[#*>`-]+", "", cleaned).strip()
            if len(cleaned) > 42:
                return cleaned[:40].rstrip() + "…"
            return cleaned or "New Operation"
        if attachments:
            first_file = attachments[0].get("filename", "Attachment")
            return f"Analysis: {first_file}"
        return "New Operation"

    def _serve_static(self, path: str):
        if path == "/" or path == "":
            path = "/index.html"

        if path == "/blume_logo.ico":
            ico_path = os.path.join(ROOT_DIR, "blume_logo.ico")
            if os.path.isfile(ico_path):
                with open(ico_path, "rb") as f:
                    data = f.read()
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
                self.wfile.flush()
                return

        safe_rel = os.path.normpath(path.lstrip("/"))
        if safe_rel.startswith(".."):
            return self._send_json({"error": "Forbidden"}, 403)

        full_path = os.path.join(FRONTEND_DIR, safe_rel)
        if not os.path.isfile(full_path):
            full_path = os.path.join(FRONTEND_DIR, "index.html")
            if not os.path.isfile(full_path):
                return self._send_json({"error": "Frontend asset not found"}, 404)

        ctype, _ = mimetypes.guess_type(full_path)
        if not ctype:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"

        with open(full_path, "rb") as f:
            content = f.read()

        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(content)
        self.wfile.flush()


class GemOSHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def find_free_port(preferred: int = 8765) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(host: str = "127.0.0.1", port: Optional[int] = None) -> tuple[ThreadingHTTPServer, int]:
    actual_port = port or find_free_port(8765)
    server = GemOSHTTPServer((host, actual_port), GemOSRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, actual_port
