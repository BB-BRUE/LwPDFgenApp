# LwPDFgenApp

Der Projektordner ist eigenständig. Für die Installation auf dem Linux-Webserver muss ausschließlich `LwPDFgenApp` kopiert werden.

Die Weboberfläche ergänzt die bestehende Pipeline um:

- eine statische Verwaltungsseite `static/index.html`
- eine statische Fehlerseite `static/pdf-nicht-gefunden.html`
- Upload einer PDF und direkte Umwandlung in die mobile Fassung
- Verwaltung unter `https://lichtwelt.bartenbach.com/app/`
- dauerhafte Ablage der fertigen Dateien unter `data/pdf`
- öffentliche PDFs unter `https://lichtwelt.bartenbach.com/pdf/<datei>.pdf`
- QR-Code-Download für jede vorhandene PDF
- Öffnen und Löschen vorhandener PDFs
- optionalen HTTP-Basisschutz für die Verwaltungsoberfläche

Die PDF-Links unter `/pdf/<datei>.pdf` bleiben bewusst ohne Anmeldung erreichbar, damit die heruntergeladenen QR-Codes auf Smartphones funktionieren. Upload, Liste, QR-Erzeugung und Löschen sind geschützt, sobald Benutzername und Passwort gesetzt wurden.

## Start mit Docker Compose

Im Projektordner:

```bash
cp .env.example .env
```

In `.env` mindestens die öffentliche Subdomain und ein starkes Passwort eintragen:

```dotenv
PUBLIC_BASE_URL=https://lichtwelt.bartenbach.com
APP_USERNAME=admin
APP_PASSWORD=ein-langes-zufaelliges-passwort
```

Prüfen, wie das Docker-Netz des SWAG-Containers heißt. Der Standard ist `swag`; bei Bedarf `SWAG_NETWORK` in `.env` ändern. Danach starten:

```bash
docker compose up -d --build
```

Die Dateien bleiben im Host-Verzeichnis `data/pdf` erhalten. Der Anwendungscontainer veröffentlicht absichtlich keinen Host-Port und ist nur im gemeinsamen Docker-Netz erreichbar.

## SWAG-Proxy

`deploy/swag/lichtwelt.subdomain.conf.example` enthält eine vollständige, zusammengeführte Serverkonfiguration für `lichtwelt.bartenbach.com`. Sie kombiniert:

- die statische Lichtwelt-Website unter `/`
- die LwPDFgen-Verwaltung unter `/app/`
- die IP-geschützte PDF-Auslieferung unter `/pdf/`
- die Weiterleitung nicht erlaubter PDF-Aufrufe auf `/index.html`
- die statische Fehlerseite für fehlende PDFs

Die bisherige Lichtwelt-Konfiguration im SWAG-Volume durch diese Konfiguration ersetzen. Außerdem `static/pdf-nicht-gefunden.html` nach `/config/www/lichtwelt/pdf-nicht-gefunden.html` im SWAG-Volume kopieren. Anschließend die Nginx-Konfiguration testen und SWAG neu laden oder neu starten.

Wichtig: `PUBLIC_BASE_URL` muss exakt der von außen erreichbaren HTTPS-Adresse entsprechen. Diese Adresse wird in die QR-Codes geschrieben.

## Lokaler Entwicklungsstart

Die folgenden Befehle werden im Projektordner ausgeführt:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PDF_STORAGE_DIR=data/pdf PUBLIC_BASE_URL=http://localhost:8000 python webapp.py
```

Unter Windows lautet die Aktivierung `.venv\\Scripts\\activate`. Umgebungsvariablen werden in PowerShell mit `$env:NAME="Wert"` gesetzt.

## Einstellungen

| Variable | Standard | Zweck |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | aktuelle Request-Adresse | Öffentliche Basisadresse für QR-Codes |
| `APP_USERNAME` / `APP_PASSWORD` | leer | Optionaler Schutz der Verwaltung |
| `MAX_UPLOAD_MB` | `50` | Maximale Upload-Größe |
| `PDF_STORAGE_DIR` | `data/pdf` | Ablage der mobilen PDFs, relativ zum Projektordner |
| `PDF_BRAND_LABEL` | `Bartenbach · Lichtkonzept` | Markenlabel im mobilen PDF |
| `PDF_WIDTH_MM` | `108` | Seitenbreite der mobilen PDF |
| `PDF_MARGIN_MM` | `15` | Seitenrand der mobilen PDF |

Gesundheitsprüfung: `GET /app/api/health`.
