from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from reportlab.pdfgen import canvas


def sample_pdf() -> bytes:
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(72, 760, "Mobile Test PDF")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 730, "Ein einfaches Testdokument")
    pdf.save()
    return stream.getvalue()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PDF_STORAGE_DIR", str(tmp_path / "pdf"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://pdf.example.com")
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    try:
        from app.webapp import create_app
    except ModuleNotFoundError:
        from webapp import create_app

    app = create_app({"TESTING": True, "MAX_CONTENT_LENGTH": 2 * 1024 * 1024})
    return app.test_client()


def test_upload_list_qr_and_delete(client):
    response = client.post(
        "/app/api/documents",
        data={"file": (io.BytesIO(sample_pdf()), "Beispiel Licht.pdf")},
        content_type="multipart/form-data",
        headers={"X-LwPDFgen": "web"},
    )
    assert response.status_code == 201
    name = response.json["document"]["name"]
    assert name == "Beispiel_Licht_Mobile.pdf"

    listing = client.get("/app/api/documents")
    assert listing.status_code == 200
    assert listing.json["documents"][0]["url"] == f"https://pdf.example.com/pdf/{name}"

    pdf = client.get(f"/pdf/{name}")
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF-")
    pdf.close()

    qr = client.get(f"/app/api/documents/{name}/qr")
    assert qr.status_code == 200
    assert qr.mimetype == "image/png"
    assert qr.data.startswith(b"\x89PNG")
    qr_image = Image.open(io.BytesIO(qr.data)).convert("RGB")
    center = qr_image.width // 2
    center_pixels = qr_image.crop((center - 100, center - 100, center + 100, center + 100)).getdata()
    assert (250, 150, 30) in center_pixels
    qr.close()

    deleted = client.delete(f"/app/api/documents/{name}", headers={"X-LwPDFgen": "web"})
    assert deleted.status_code == 200
    assert client.get(f"/pdf/{name}").status_code == 404


def test_rejects_non_pdf(client):
    response = client.post(
        "/app/api/documents",
        data={"file": (io.BytesIO(b"not a pdf"), "fake.pdf")},
        content_type="multipart/form-data",
        headers={"X-LwPDFgen": "web"},
    )
    assert response.status_code == 415


def test_path_traversal_is_rejected(client):
    response = client.get("/pdf/..%2Fsecret.pdf")
    assert response.status_code == 404
    assert b"Diese PDF ist nicht mehr verf" in response.data


def test_mutations_require_application_header(client):
    response = client.post(
        "/app/api/documents",
        data={"file": (io.BytesIO(sample_pdf()), "Beispiel.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 403


def test_static_app_routes(client):
    index = client.get("/app/")
    assert index.status_code == 200
    assert b"{{" not in index.data
    assert b'/app/static/app.js' in index.data
    assert client.get("/app/static/app.css").status_code == 200
    assert client.get("/app/api/health").json == {"status": "ok"}


def test_public_pages_are_served_from_data_directory(client, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "index.html").write_text("public start", encoding="utf-8")
    (data / "pdf-nicht-gefunden.html").write_text("public 404", encoding="utf-8")
    (data / "bartenbach-logo.png").write_bytes(b"logo")
    (data / "wifi-lw-internet-qr.png").write_bytes(b"qr")

    assert client.get("/").data == b"public start"
    assert client.get("/index.html").data == b"public start"
    assert client.get("/pdf-nicht-gefunden.html").data == b"public 404"
    assert client.get("/pdf/missing.pdf").data == b"public 404"
    assert client.get("/site-assets/bartenbach-logo.png").data == b"logo"
    assert client.get("/site-assets/wifi-lw-internet-qr.png").data == b"qr"
    assert client.get("/site-assets/unknown.png").status_code == 404
