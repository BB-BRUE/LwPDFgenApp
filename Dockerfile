FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PDF_STORAGE_DIR=/app/pdf \
    PORT=8000

WORKDIR /app

RUN addgroup --system lwpdfgen && adduser --system --ingroup lwpdfgen lwpdfgen

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY mobile_pdf_pipeline.py webapp.py ./
COPY static ./static

RUN mkdir -p /app/pdf && chown -R lwpdfgen:lwpdfgen /app
USER lwpdfgen

EXPOSE 8000
VOLUME ["/app/pdf"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/app/api/health', timeout=3)" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "webapp:app"]
