#!/usr/bin/env python3
"""Convert template-based A4 flyers to mobile PDFs and publish changed files."""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import smtplib
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import pdfplumber
from PIL import Image as PILImage, ImageDraw
from pypdf import PdfReader
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ORANGE = HexColor("#fa961e")  # RGB 250/150/30; brand reference CMYK 0/50/100/0.
BLACK = HexColor("#242424")
GREY = HexColor("#777777")
LIGHT_GREY = HexColor("#f7f7f7")
RULE_GREY = HexColor("#d8d8d8")
MM = 72.0 / 25.4
STATE_VERSION = 1
QR_LOGO_PATH = Path(__file__).resolve().parent / "static" / "dot_bartenbach.png"
PDF_BRAND_LOGO_PATH = Path(__file__).resolve().parent / "static" / "bartenbach_master.png"


@dataclass
class TextLine:
    text: str
    top: float
    x0: float
    x1: float
    size: float
    bold: bool = False


@dataclass
class SourceImage:
    data: bytes
    width: float
    height: float
    caption: str = ""


@dataclass
class MobileContent:
    title: str
    subtitle: str = ""
    intro_heading: str = ""
    paragraphs: list[str] = field(default_factory=list)
    fact_heading: str = "Daten und Fakten"
    facts: list[str] = field(default_factory=list)
    value_heading: str = "Mehrwert"
    values: list[str] = field(default_factory=list)
    images: list[SourceImage] = field(default_factory=list)


def deep_get(config: dict[str, Any], path: str, default: Any = None) -> Any:
    value: Any = config
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def resolve(base: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def clean_text(value: str) -> str:
    value = value.replace("\u00ad", "").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", value).strip()


def safe_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[\s]+", "_", normalized)
    normalized = re.sub(r"[^\w.-]", "_", normalized, flags=re.UNICODE)
    return re.sub(r"_+", "_", normalized).strip("._") or "document"


def group_lines(words: list[dict[str, Any]], page_width: float) -> list[TextLine]:
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        row = next((candidate for candidate in reversed(rows[-8:]) if abs(candidate[0]["top"] - word["top"]) <= 1.2), None)
        if row is None:
            row = []
            rows.append(row)
        row.append(word)

    lines: list[TextLine] = []
    for row in rows:
        row.sort(key=lambda item: item["x0"])
        chunks: list[list[dict[str, Any]]] = [[]]
        previous = None
        for word in row:
            gap = word["x0"] - previous["x1"] if previous else 0
            crosses_column = previous and previous["x0"] < page_width / 2 <= word["x0"]
            if previous and (gap > 32 or (crosses_column and gap > 14)):
                chunks.append([])
            chunks[-1].append(word)
            previous = word
        for chunk in chunks:
            if not chunk:
                continue
            text = clean_text(" ".join(item["text"] for item in chunk))
            if not text:
                continue
            fontname = " ".join(str(item.get("fontname", "")) for item in chunk)
            lines.append(
                TextLine(
                    text=text,
                    top=sum(float(item["top"]) for item in chunk) / len(chunk),
                    x0=min(float(item["x0"]) for item in chunk),
                    x1=max(float(item["x1"]) for item in chunk),
                    size=max(float(item.get("size", 8)) for item in chunk),
                    bold="bold" in fontname.lower(),
                )
            )
    return sorted(lines, key=lambda item: (item.top, item.x0))


def join_paragraphs(lines: list[TextLine]) -> list[str]:
    if not lines:
        return []
    paragraphs: list[list[str]] = [[]]
    previous: TextLine | None = None
    for line in sorted(lines, key=lambda item: item.top):
        if previous and line.top - previous.top > max(1.55 * previous.size, 15):
            paragraphs.append([])
        paragraphs[-1].append(line.text)
        previous = line
    return [clean_text(" ".join(parts)) for parts in paragraphs if parts]


def bullet_items(lines: list[TextLine]) -> list[str]:
    bullets = ("■", "▪", "•", "●", "◆")
    markers = sorted((line for line in lines if line.text.strip().startswith(bullets)), key=lambda item: item.top)
    content = sorted((line for line in lines if not line.text.strip().startswith(bullets)), key=lambda item: item.top)
    starts: list[float] = []
    for marker in markers:
        nearby = [line for line in content if marker.top - 7 <= line.top <= marker.top + 7]
        starts.append(min(nearby, key=lambda item: abs(item.top - marker.top)).top if nearby else marker.top)
    items: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else math.inf
        parts = [line.text for line in content if line.top >= start - 0.5 and line.top < end - 0.5]
        value = clean_text(" ".join(parts))
        if value:
            items.append(value)
    return items


def heading_case(value: str) -> str:
    if not value or value != value.upper():
        return value
    result = value.title()
    for word in ("Und", "Oder", "Mit", "Für", "Von", "Der", "Die", "Das"):
        result = result.replace(f" {word} ", f" {word.lower()} ")
    return result


def extract_image_data(pdf_page: Any, plumber_image: dict[str, Any]) -> bytes | None:
    target = str(plumber_image.get("name", ""))
    for pdf_image in pdf_page.images:
        if Path(pdf_image.name).stem == target:
            try:
                pil = pdf_image.image
                output = io.BytesIO()
                if pil.mode not in ("RGB", "L"):
                    pil = pil.convert("RGB")
                pil.save(output, format="JPEG", quality=88, optimize=True)
                return output.getvalue()
            except Exception:
                return pdf_image.data
    return None


def extract_page(source: Path, page_number: int = 0) -> MobileContent:
    with pdfplumber.open(source) as document:
        page = document.pages[page_number]
        words = page.extract_words(extra_attrs=["size", "fontname"])
        lines = group_lines(words, page.width)
        if not lines:
            raise ValueError(f"Keine extrahierbaren Texte auf Seite {page_number + 1}: {source.name}")

        candidates = [line for line in lines if line.top < page.height * 0.35 and len(line.text) > 2]
        title = max(candidates, key=lambda item: (item.size, -item.top))
        following = [line for line in lines if line.top > title.top + 2 and line.x0 < page.width * 0.65]
        subtitle = following[0] if following else None
        headings = [
            line for line in following
            if line.top > (subtitle.top + 2 if subtitle else title.top + 2)
            and (line.bold or line.size >= max(12, title.size * 0.65))
        ]
        intro_heading = headings[0] if headings else None

        bullet_lines = [line for line in lines if line.text.strip().startswith(("■", "▪", "•", "●", "◆"))]
        first_bullet_top = min((line.top for line in bullet_lines), default=page.height * 0.62)
        column_headings = [
            line for line in lines
            if intro_heading and line.top > intro_heading.top + 2
            and line.top < first_bullet_top
            and line.size >= 12
        ]
        list_top = min((line.top for line in column_headings), default=first_bullet_top - 10)
        intro_lines = [
            line for line in lines
            if intro_heading and line.top > intro_heading.top + 2 and line.top < list_top - 2
            and not line.text.strip().startswith(("■", "▪", "•", "●", "◆"))
        ]

        useful_images = [
            item for item in page.images
            if (item["x1"] - item["x0"]) * (item["bottom"] - item["top"]) > page.width * page.height * 0.02
            and item["top"] > page.height * 0.25
        ]
        list_bottom = min((float(item["top"]) for item in useful_images), default=page.height)
        left_lines = [line for line in lines if line.x0 < page.width / 2 and list_top <= line.top < list_bottom]
        right_lines = [line for line in lines if line.x0 >= page.width / 2 and list_top <= line.top < list_bottom]
        left_heading_lines = [line for line in column_headings if line.x0 < page.width / 2]
        right_heading_lines = [line for line in column_headings if line.x0 >= page.width / 2]

        reader_page = PdfReader(str(source)).pages[page_number]
        images: list[SourceImage] = []
        for item in sorted(useful_images, key=lambda value: (value["x0"], value["top"])):
            data = extract_image_data(reader_page, item)
            if not data:
                continue
            caption_lines = [
                line for line in lines
                if line.top >= item["bottom"] - 1 and line.top <= item["bottom"] + 18
                and line.x1 >= item["x0"] and line.x0 <= item["x1"]
                and line.size <= 10
            ]
            images.append(
                SourceImage(
                    data=data,
                    width=float(item["x1"] - item["x0"]),
                    height=float(item["bottom"] - item["top"]),
                    caption=clean_text(" ".join(line.text for line in caption_lines)),
                )
            )

        return MobileContent(
            title=title.text,
            subtitle=subtitle.text if subtitle else "",
            intro_heading=intro_heading.text if intro_heading else "",
            paragraphs=join_paragraphs(intro_lines),
            fact_heading=clean_text(" ".join(line.text for line in sorted(left_heading_lines, key=lambda item: item.top))) or "Daten und Fakten",
            facts=bullet_items(left_lines),
            value_heading=clean_text(" ".join(line.text for line in sorted(right_heading_lines, key=lambda item: item.top))) or "Mehrwert",
            values=bullet_items(right_lines),
            images=images,
        )


def wrap(value: str, font: str, size: float, width: float) -> list[str]:
    words = clean_text(value).split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if stringWidth(trial, font, size) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class MobileLayout:
    def __init__(self, content: MobileContent, width: float, margin: float, brand_logo: Path, footer: str):
        self.content = content
        self.width = width
        self.margin = margin
        self.inner = width - 2 * margin
        self.brand_logo = brand_logo
        self.footer = footer

    def _brand_logo(self) -> tuple[ImageReader, float, float]:
        if not self.brand_logo.is_file():
            raise FileNotFoundError(f"PDF-Markenlogo fehlt: {self.brand_logo}")
        with PILImage.open(self.brand_logo) as source:
            logo = source.convert("RGBA")
            alpha_box = logo.getchannel("A").getbbox()
            if alpha_box:
                logo = logo.crop(alpha_box)
            data = io.BytesIO()
            logo.save(data, format="PNG", optimize=True)
        logo_width = min(self.inner * 0.72, 58 * MM)
        logo_height = logo_width * logo.height / logo.width
        return ImageReader(data), logo_width, logo_height

    def _text_height(self, value: str, font: str, size: float, leading: float, width: float | None = None) -> float:
        return len(wrap(value, font, size, width or self.inner)) * leading

    def height(self) -> float:
        c = self.content
        _, _, logo_height = self._brand_logo()
        total = 24 + logo_height + 28
        total += self._text_height(c.title, "Helvetica-Bold", 18, 21) + 12
        total += self._text_height(c.subtitle, "Helvetica", 8, 10) + 47
        total += 1 + 24
        total += self._text_height(c.intro_heading, "Helvetica-Bold", 11, 14) + 13
        for paragraph in c.paragraphs:
            total += self._text_height(paragraph, "Helvetica", 7.2, 10.2) + 7
        total += 23 + 1 + 21
        total += self._text_height(heading_case(c.fact_heading), "Helvetica-Bold", 11, 13, self.inner * 0.8) + 17
        facts_h = sum(self._text_height(item, "Helvetica", 7, 9.2, self.inner - 32) + 5 for item in c.facts)
        total += max(72, facts_h + 18) + 26 + 1 + 21
        total += self._text_height(heading_case(c.value_heading), "Helvetica-Bold", 11, 13, self.inner * 0.8) + 16
        total += sum(self._text_height(item, "Helvetica", 7, 9.2, self.inner - 16) + 5 for item in c.values)
        total += 27 + 1 + 22 + 13 + 28
        for image in c.images:
            image_h = self.inner * image.height / image.width
            total += image_h + (10 if image.caption else 3) + 22
        total += 20
        return max(500, math.ceil(total))

    def draw(self, output: Path) -> None:
        height = self.height()
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(output), pagesize=(self.width, height), pageCompression=1)
        pdf.setTitle(self.content.title)
        y = height - 28

        def draw_wrapped(value: str, font: str, size: float, leading: float, color: Color = BLACK,
                         x: float | None = None, max_width: float | None = None) -> None:
            nonlocal y
            pdf.setFont(font, size)
            pdf.setFillColor(color)
            for line in wrap(value, font, size, max_width or self.inner):
                pdf.drawString(self.margin if x is None else x, y, line)
                y -= leading

        logo, logo_width, logo_height = self._brand_logo()
        pdf.drawImage(
            logo,
            self.margin,
            y - logo_height,
            logo_width,
            logo_height,
            preserveAspectRatio=True,
            mask="auto",
        )
        y -= logo_height + 28
        draw_wrapped(self.content.title, "Helvetica-Bold", 18, 21)
        y -= 3
        draw_wrapped(self.content.subtitle, "Helvetica", 8, 10, GREY)
        y -= 37
        pdf.setStrokeColor(ORANGE)
        pdf.setLineWidth(1.1)
        pdf.line(0, y, self.width, y)
        y -= 24
        draw_wrapped(self.content.intro_heading, "Helvetica-Bold", 11, 14)
        y -= 3
        for paragraph in self.content.paragraphs:
            draw_wrapped(paragraph, "Helvetica", 7.2, 10.2, GREY)
            y -= 7
        y -= 15
        pdf.setStrokeColor(RULE_GREY)
        pdf.setLineWidth(0.45)
        pdf.line(0, y, self.width, y)
        y -= 22

        draw_wrapped(heading_case(self.content.fact_heading), "Helvetica-Bold", 11, 13)
        y -= 8
        fact_height = max(72, sum(self._text_height(item, "Helvetica", 7, 9.2, self.inner - 32) + 5 for item in self.content.facts) + 18)
        box_top = y
        pdf.setFillColor(LIGHT_GREY)
        pdf.rect(self.margin, y - fact_height, self.inner, fact_height, fill=1, stroke=0)
        pdf.setFillColor(ORANGE)
        pdf.rect(self.margin, y - fact_height, 1.8, fact_height, fill=1, stroke=0)
        y -= 11
        for item in self.content.facts:
            pdf.setFillColor(ORANGE)
            pdf.circle(self.margin + 13, y + 1.3, 1.1, fill=1, stroke=0)
            draw_wrapped(item, "Helvetica", 7, 9.2, GREY, self.margin + 25, self.inner - 32)
            y -= 5
        y = box_top - fact_height - 26
        pdf.setStrokeColor(RULE_GREY)
        pdf.line(0, y, self.width, y)
        y -= 22

        draw_wrapped(heading_case(self.content.value_heading), "Helvetica-Bold", 11, 13, BLACK, max_width=self.inner * 0.85)
        y -= 7
        for item in self.content.values:
            pdf.setFillColor(ORANGE)
            pdf.circle(self.margin + 2, y + 1.2, 1.1, fill=1, stroke=0)
            draw_wrapped(item, "Helvetica", 7, 9.2, GREY, self.margin + 13, self.inner - 16)
            y -= 5
        y -= 18
        pdf.setStrokeColor(RULE_GREY)
        pdf.line(0, y, self.width, y)
        y -= 24
        draw_wrapped("Referenzen", "Helvetica-Bold", 11, 13)
        y -= 18
        for image in self.content.images:
            image_height = self.inner * image.height / image.width
            reader = ImageReader(io.BytesIO(image.data))
            pdf.drawImage(reader, self.margin, y - image_height, self.inner, image_height, preserveAspectRatio=True, mask="auto")
            y -= image_height
            if image.caption:
                y -= 5
                draw_wrapped(image.caption, "Helvetica", 4.2, 6, GREY)
            y -= 18
        draw_wrapped(self.footer, "Helvetica", 3.5, 5, HexColor("#b0b0b0"))
        pdf.save()


def convert_pdf(source: Path, output: Path, config: dict[str, Any]) -> None:
    width = float(deep_get(config, "conversion.width_mm", 108)) * MM
    margin = float(deep_get(config, "conversion.margin_mm", 15)) * MM
    brand_logo_value = str(deep_get(config, "conversion.brand_logo", PDF_BRAND_LOGO_PATH))
    brand_logo = Path(brand_logo_value).expanduser()
    if not brand_logo.is_absolute():
        brand_logo = (Path(__file__).resolve().parent / brand_logo).resolve()
    footer = str(deep_get(config, "conversion.footer", "Smartphone-optimierte Fassung · automatisch aus der Original-PDF erstellt"))
    content = extract_page(source)
    MobileLayout(content, width, margin, brand_logo, footer).draw(output)


def qr_png_bytes(url: str, size: int = 900) -> bytes:
    widget = QrCodeWidget(url, barLevel="H")
    widget.qr.make()
    modules = widget.qr.modules
    border = 4
    module_count = len(modules)
    pixels_per_module = max(1, size // (module_count + 2 * border))
    actual_size = (module_count + 2 * border) * pixels_per_module
    image = PILImage.new("RGB", (actual_size, actual_size), "white")
    draw = ImageDraw.Draw(image)
    for row, values in enumerate(modules):
        for column, enabled in enumerate(values):
            if enabled:
                x0 = (column + border) * pixels_per_module
                y0 = (row + border) * pixels_per_module
                draw.rectangle(
                    (x0, y0, x0 + pixels_per_module - 1, y0 + pixels_per_module - 1),
                    fill="black",
                )

    logo_size = max(pixels_per_module * 7, round(actual_size * 0.21))
    with PILImage.open(QR_LOGO_PATH) as source_logo:
        logo = source_logo.convert("RGBA").resize(
            (logo_size, logo_size),
            PILImage.Resampling.LANCZOS,
        )
        logo_layer = PILImage.new("RGBA", (logo_size, logo_size), "white")
        logo_layer.alpha_composite(logo)

    center = actual_size // 2
    image.paste(
        logo_layer.convert("RGB"),
        (center - logo_size // 2, center - logo_size // 2),
    )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def qr_png(url: str, output: Path, size: int = 900) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(qr_png_bytes(url, size))


def public_url(config: dict[str, Any], filename: str) -> str:
    base = str(deep_get(config, "publish.base_url", "")).rstrip("/")
    if not base:
        raise ValueError("publish.base_url fehlt")
    return f"{base}/{quote(filename)}"


def upload_pdf(pdf: Path, config: dict[str, Any]) -> None:
    host = str(deep_get(config, "publish.host", "")).strip()
    user = str(deep_get(config, "publish.user", "")).strip()
    remote_directory = str(deep_get(config, "publish.remote_directory", "")).strip().rstrip("/")
    if not host or not user or not remote_directory:
        raise ValueError("Für SCP sind publish.host, publish.user und publish.remote_directory erforderlich")
    command = [str(deep_get(config, "publish.scp_executable", "scp")), "-B"]
    identity = str(deep_get(config, "publish.identity_file", "")).strip()
    if identity:
        command += ["-i", str(Path(identity).expanduser())]
    port = int(deep_get(config, "publish.port", 22))
    if port != 22:
        command += ["-P", str(port)]
    command += [str(pdf), f"{user}@{host}:{remote_directory}/{pdf.name}"]
    subprocess.run(command, check=True)


def send_email(pdf: Path, qr: Path, url: str, config: dict[str, Any]) -> None:
    host = str(deep_get(config, "email.smtp_host", "")).strip()
    recipients = deep_get(config, "email.to", [])
    if isinstance(recipients, str):
        recipients = [recipients]
    if not host or not recipients:
        raise ValueError("Für E-Mail sind email.smtp_host und email.to erforderlich")

    sender = str(deep_get(config, "email.from", "")).strip()
    if not sender:
        raise ValueError("email.from fehlt")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = str(deep_get(config, "email.subject", "Neue mobile PDF: {filename}")).format(filename=pdf.name)
    message.set_content(
        f"Eine neue mobile PDF wurde veröffentlicht.\n\nDatei: {pdf.name}\nLink: {url}\n\nDer QR-Code ist angehängt."
    )
    message.add_attachment(qr.read_bytes(), maintype="image", subtype="png", filename=qr.name)

    authentication = bool(deep_get(config, "email.authentication", True))
    port = int(deep_get(config, "email.smtp_port", 587))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if bool(deep_get(config, "email.starttls", True)):
            smtp.starttls()
        if authentication:
            username_env = str(deep_get(config, "email.username_env", "MOBILE_PDF_SMTP_USER"))
            password_env = str(deep_get(config, "email.password_env", "MOBILE_PDF_SMTP_PASSWORD"))
            username = os.getenv(username_env, "")
            password = os.getenv(password_env, "")
            if not username:
                raise ValueError(f"SMTP-Authentifizierung ist aktiv, aber {username_env} ist nicht gesetzt")
            smtp.login(username, password)
        smtp.send_message(message)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "files": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != STATE_VERSION:
        raise ValueError(f"Nicht unterstützte Statusdatei-Version: {data.get('version')}")
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
        temp_name = stream.name
    Path(temp_name).replace(path)


def scan_sources(input_directory: Path, output_directory: Path, suffix: str, recursive: bool) -> Iterable[Path]:
    for source in sorted(input_directory.rglob("*.pdf") if recursive else input_directory.glob("*.pdf")):
        if suffix.lower() in source.stem.lower():
            continue
        if output_directory == source.parent or output_directory in source.parents:
            continue
        yield source


def run(config_path: Path, force: bool, dry_run: bool, no_upload: bool, no_email: bool) -> int:
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)
    base = config_path.parent.resolve()
    input_directory = resolve(base, deep_get(config, "paths.input_directory", "incoming"))
    output_directory = resolve(base, deep_get(config, "paths.output_directory", "output/mobile"))
    state_path = resolve(base, deep_get(config, "paths.state_file", ".mobile_pdf_state.json"))
    suffix = str(deep_get(config, "paths.mobile_suffix", "_Mobile"))
    state = load_state(state_path)
    file_state: dict[str, Any] = state.setdefault("files", {})
    changed: list[Path] = []
    recursive = bool(deep_get(config, "paths.recursive", True))
    for source in scan_sources(input_directory, output_directory, suffix, recursive):
        key = source.relative_to(input_directory).as_posix()
        stamp = source.stat().st_mtime_ns
        if force or stamp != int(file_state.get(key, {}).get("mtime_ns", -1)):
            changed.append(source)

    if not changed:
        print("Keine neuen oder geänderten PDFs gefunden.")
        if not dry_run:
            save_state(state_path, state)
        return 0

    print(f"{len(changed)} neue/geänderte PDF(s):")
    for source in changed:
        print(f"  - {source}")
    if dry_run:
        return 0

    upload_enabled = bool(deep_get(config, "publish.enabled", False)) and not no_upload
    email_enabled = bool(deep_get(config, "email.enabled", False)) and not no_email
    failures = 0
    for source in changed:
        key = source.relative_to(input_directory).as_posix()
        try:
            filename = f"{safe_stem(source.stem)}{suffix}.pdf"
            output = output_directory / filename
            qr = source.parent / f"{output.stem}_QR.png"
            convert_pdf(source, output, config)
            url = public_url(config, output.name)
            qr_png(url, qr)
            if upload_enabled:
                upload_pdf(output, config)
            if email_enabled:
                send_email(output, qr, url, config)
            file_state[key] = {
                "mtime_ns": source.stat().st_mtime_ns,
                "output": output.name,
                "url": url,
                "processed_utc": datetime.now(timezone.utc).isoformat(),
            }
            print(f"OK: {source.name} -> {output.name}")
        except Exception as exc:
            failures += 1
            print(f"FEHLER: {source.name}: {exc}", file=sys.stderr)
    save_state(state_path, state)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Neue/geänderte PDFs mobil aufbereiten, hochladen und melden.")
    parser.add_argument("--config", type=Path, default=Path("config.toml"), help="Pfad zur TOML-Konfiguration")
    parser.add_argument("--force", action="store_true", help="Alle Quell-PDFs erneut verarbeiten")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, welche PDFs verarbeitet würden")
    parser.add_argument("--no-upload", action="store_true", help="SCP-Upload für diesen Lauf deaktivieren")
    parser.add_argument("--no-email", action="store_true", help="E-Mail für diesen Lauf deaktivieren")
    args = parser.parse_args()
    return run(args.config.resolve(), args.force, args.dry_run, args.no_upload, args.no_email)


if __name__ == "__main__":
    raise SystemExit(main())
