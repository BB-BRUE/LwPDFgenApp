#!/usr/bin/env python3
"""Web interface for converting and publishing mobile PDFs."""

from __future__ import annotations

import hmac
import io
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from pypdf import PdfReader
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    from .mobile_pdf_pipeline import convert_pdf, qr_png_bytes, safe_stem
except ImportError:  # Direct execution inside the standalone app directory.
    from mobile_pdf_pipeline import convert_pdf, qr_png_bytes, safe_stem


APP_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = APP_ROOT / "static"
APP_PREFIX = "/app"
PDF_SUFFIX = "_Mobile"
UPLOAD_LOCK = threading.Lock()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def data_directory() -> Path:
    configured = os.getenv("APP_DATA_DIR", "data")
    path = Path(configured).expanduser()
    return (path if path.is_absolute() else APP_ROOT / path).resolve()


def storage_directory() -> Path:
    configured = os.getenv("PDF_STORAGE_DIR")
    if configured:
        path = Path(configured).expanduser()
        return (path if path.is_absolute() else APP_ROOT / path).resolve()
    return data_directory() / "pdf"


def public_page(filename: str) -> Response:
    root = data_directory()
    if (root / filename).is_file():
        return send_from_directory(root, filename)
    return send_from_directory(STATIC_ROOT, filename)

def conversion_config() -> dict:
    return {
        "conversion": {
            "width_mm": float(os.getenv("PDF_WIDTH_MM", "108")),
            "margin_mm": float(os.getenv("PDF_MARGIN_MM", "15")),
            "brand_label": os.getenv("PDF_BRAND_LABEL", "Bartenbach · Lichtkonzept"),
            "footer": os.getenv(
                "PDF_FOOTER",
                "Smartphone-optimierte Fassung · automatisch aus der Original-PDF erstellt",
            ),
        }
    }


def public_pdf_url(filename: str) -> str:
    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base_url:
        return f"{base_url}/pdf/{quote(filename)}"
    return request.url_root.rstrip("/") + f"/pdf/{quote(filename)}"


def safe_pdf_path(filename: str) -> Path:
    if not filename or filename != Path(filename).name or not filename.lower().endswith(".pdf"):
        raise ValueError("Ungültiger Dateiname")
    root = storage_directory()
    candidate = (root / filename).resolve()
    if candidate.parent != root:
        raise ValueError("Ungültiger Dateipfad")
    return candidate


def unique_output_path(source_stem: str) -> Path:
    root = storage_directory()
    base = f"{safe_stem(source_stem)}{PDF_SUFFIX}"
    candidate = root / f"{base}.pdf"
    counter = 2
    while candidate.exists():
        candidate = root / f"{base}-{counter}.pdf"
        counter += 1
    return candidate


def temporary_directory() -> Path:
    path = storage_directory() / ".tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_record(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "url": public_pdf_url(path.name),
    }


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.update(
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024,
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)

    if env_bool("TRUST_PROXY_HEADERS", True):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    storage_directory().mkdir(parents=True, exist_ok=True)

    @app.before_request
    def require_auth() -> Response | None:
        if (
            request.path == f"{APP_PREFIX}/api/health"
            or request.path == f"{APP_PREFIX}/static/app.css"
            or request.path.startswith("/pdf/")
            or request.path in {"/", "/index.html", "/pdf-nicht-gefunden.html"}
        ):
            return None
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("X-LwPDFgen") != "web":
            return jsonify(error="Ungültige Anfrage."), 403
        username = os.getenv("APP_USERNAME", "").strip()
        password = os.getenv("APP_PASSWORD", "")
        if not username and not password:
            return None
        if not username or not password:
            return Response("APP_USERNAME und APP_PASSWORD müssen gemeinsam gesetzt sein.", 503)
        supplied = request.authorization
        valid = bool(
            supplied
            and hmac.compare_digest(supplied.username or "", username)
            and hmac.compare_digest(supplied.password or "", password)
        )
        if valid:
            return None
        return Response(
            "Anmeldung erforderlich",
            401,
            {"WWW-Authenticate": 'Basic realm="LwPDFgen", charset="UTF-8"'},
        )

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'self'; frame-ancestors 'self'",
        )
        return response

    @app.get(APP_PREFIX)
    @app.get(f"{APP_PREFIX}/")
    def index() -> Response:
        return send_from_directory(STATIC_ROOT, "index.html")

    @app.get("/")
    @app.get("/index.html")
    def public_index() -> Response:
        return public_page("index.html")

    @app.get("/pdf-nicht-gefunden.html")
    def pdf_not_found() -> Response:
        return public_page("pdf-nicht-gefunden.html")

    @app.get(f"{APP_PREFIX}/static/<path:filename>")
    def static_asset(filename: str) -> Response:
        return send_from_directory(STATIC_ROOT, filename)

    @app.get(f"{APP_PREFIX}/api/health")
    def health() -> Response:
        return jsonify(status="ok")

    @app.get(f"{APP_PREFIX}/api/documents")
    def list_documents() -> Response:
        documents = [file_record(path) for path in storage_directory().glob("*.pdf") if path.is_file()]
        documents.sort(key=lambda item: item["created_at"], reverse=True)
        return jsonify(documents=documents)

    @app.post(f"{APP_PREFIX}/api/documents")
    def upload_document() -> tuple[Response, int] | Response:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify(error="Bitte eine PDF-Datei auswählen."), 400
        if Path(upload.filename).suffix.lower() != ".pdf":
            return jsonify(error="Es sind nur PDF-Dateien erlaubt."), 415

        temp_root = temporary_directory()
        source_fd, source_name = tempfile.mkstemp(prefix="upload-", suffix=".pdf", dir=temp_root)
        os.close(source_fd)
        source = Path(source_name)
        temp_output: Path | None = None
        try:
            upload.save(source)
            with source.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    return jsonify(error="Die hochgeladene Datei ist keine gültige PDF."), 415
                stream.seek(0)
                if len(PdfReader(stream, strict=False).pages) == 0:
                    return jsonify(error="Die PDF enthält keine Seiten."), 422

            with UPLOAD_LOCK:
                output = unique_output_path(Path(upload.filename).stem)
                output_fd, output_name = tempfile.mkstemp(prefix="convert-", suffix=".pdf", dir=temp_root)
                os.close(output_fd)
                temp_output = Path(output_name)
                convert_pdf(source, temp_output, conversion_config())
                temp_output.replace(output)
                temp_output = None

            return jsonify(document=file_record(output)), 201
        except Exception as exc:
            app.logger.exception("PDF conversion failed")
            return jsonify(error=f"Die PDF konnte nicht verarbeitet werden: {exc}"), 422
        finally:
            source.unlink(missing_ok=True)
            if temp_output is not None:
                temp_output.unlink(missing_ok=True)

    @app.get(f"{APP_PREFIX}/api/documents/<path:filename>/qr")
    def download_qr(filename: str) -> Response:
        try:
            path = safe_pdf_path(filename)
        except ValueError:
            return jsonify(error="Ungültiger Dateiname."), 400
        if not path.is_file():
            return jsonify(error="PDF nicht gefunden."), 404
        content = io.BytesIO(qr_png_bytes(public_pdf_url(path.name)))
        content.seek(0)
        return send_file(
            content,
            mimetype="image/png",
            as_attachment=True,
            download_name=f"{path.stem}_QR.png",
            max_age=0,
        )

    @app.get("/pdf/<path:filename>")
    def download_pdf(filename: str) -> Response:
        try:
            path = safe_pdf_path(filename)
        except ValueError:
            return public_page("pdf-nicht-gefunden.html"), 404
        if not path.is_file():
            return public_page("pdf-nicht-gefunden.html"), 404
        return send_file(path, mimetype="application/pdf", conditional=True, max_age=0)

    @app.delete(f"{APP_PREFIX}/api/documents/<path:filename>")
    def delete_document(filename: str) -> tuple[Response, int] | Response:
        try:
            path = safe_pdf_path(filename)
        except ValueError:
            return jsonify(error="Ungültiger Dateiname."), 400
        if not path.is_file():
            return jsonify(error="PDF nicht gefunden."), 404
        path.unlink()
        return jsonify(deleted=path.name)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error: RequestEntityTooLarge) -> tuple[Response, int]:
        return jsonify(error=f"Die Datei ist größer als {os.getenv('MAX_UPLOAD_MB', '50')} MB."), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=env_bool("FLASK_DEBUG"))
