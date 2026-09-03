# LwPDFgenApp

Der Projektordner ist eigenständig. Für die Installation auf dem Linux-Webserver muss ausschließlich `LwPDFgenApp` kopiert werden.

Die Weboberfläche ergänzt die bestehende Pipeline um:

- eine Verwaltungsseite unter `/app/`
- Upload einer PDF und direkte Umwandlung in die mobile Fassung
- dauerhafte Ablage der fertigen Dateien
- öffentliche PDFs unter `/pdf/<datei>.pdf`
- QR-Code-Download für jede vorhandene PDF
- Öffnen und Löschen vorhandener PDFs
- optionalen HTTP-Basisschutz für die Verwaltungsoberfläche

Die PDF-Links unter `/pdf/<datei>.pdf` bleiben bewusst ohne Anmeldung erreichbar, damit die heruntergeladenen QR-Codes auf Smartphones funktionieren. Upload, Liste, QR-Erzeugung und Löschen sind geschützt, sobald Benutzername und Passwort gesetzt wurden.

## Ein gemeinsames Datenverzeichnis

Die Anwendung verwendet nur noch das eine, persistente Host-Verzeichnis `data`, das als `/app/data` in den Container eingebunden wird:

```text
data/
├── index.html
├── pdf-nicht-gefunden.html
└── pdf/
    └── *.pdf
```

- `data/index.html` ist die öffentliche Startseite unter `/` und `/index.html`.
- `data/pdf-nicht-gefunden.html` wird für fehlende PDFs ausgeliefert.
- `data/pdf` enthält die erzeugten mobilen PDFs und das temporäre Arbeitsverzeichnis `.tmp`.

Fehlen die beiden HTML-Dateien beim ersten Start, kopiert der Container Standardversionen aus dem Image nach `data`. Vorhandene Dateien werden nicht überschrieben. Eine bereits verwendete öffentliche Startseite sollte daher vor dem ersten Start nach `data/index.html` kopiert werden.

Die zweisprachige Beispiel-Startseite liegt unter `static/index.example.html`. Sie enthält das Bartenbach-Wortlogo und einen WLAN-QR-Code für `LW-Internet` vollständig eingebettet und benötigt keine zusätzlichen Bild- oder CSS-Dateien.

Ein separates Webroot im SWAG-Verzeichnis, beispielsweise `/config/www/lichtwelt`, wird nicht mehr benötigt. SWAG leitet Startseite, Fehlerseite, Verwaltung und PDFs an den App-Container weiter.

## Start mit Docker Compose

Im Projektordner:

```bash
cp .env.example .env
mkdir -p data/pdf
```

Falls bereits eine öffentliche Startseite existiert, diese jetzt übernehmen:

```bash
cp /pfad/zur/bisherigen/index.html data/index.html
```

In `.env` mindestens die öffentliche Subdomain und ein starkes Passwort eintragen:

```dotenv
PUBLIC_BASE_URL=https://lichtwelt.bartenbach.com
APP_USERNAME=admin
APP_PASSWORD=ein-langes-zufaelliges-passwort
```

Das gemeinsame SWAG-Netz heißt standardmäßig `swag_proxy-net`. Bei Bedarf kann `SWAG_NETWORK` in `.env` geändert werden. Danach starten:

```bash
docker compose up -d --build
```

Die Anwendung veröffentlicht absichtlich keinen Host-Port und ist nur im gemeinsamen Docker-Netz erreichbar.

### Berechtigungen des Datenverzeichnisses

Ein Host-Benutzer mit dem Namen `lwpdfgen` allein löst Bind-Mount-Berechtigungen nicht zuverlässig: Linux vergleicht die numerische UID und GID, nicht den Benutzernamen.

Der Container startet deshalb nur für die Initialisierung mit Root-Rechten. Der Entry-Point legt `data/pdf/.tmp` an, setzt den Container-Benutzer `lwpdfgen` als Eigentümer der benötigten Verzeichnisse und Dateien und startet Gunicorn anschließend als dieser unprivilegierte Benutzer. Die Webanwendung selbst läuft nicht als Root. Auf einem normalen lokalen Linux-Dateisystem ist deshalb kein zusätzlicher Host-Benutzer und kein manuelles `chmod 777` erforderlich.

Bei Dateisystemen, die `chown` verbieten, etwa manchen NFS- oder Rootless-Konfigurationen, müssen UID/GID des Host-Verzeichnisses stattdessen numerisch an den Container-Benutzer angepasst werden.

## SWAG-Proxy

`deploy/swag/lichtwelt.subdomain.conf.example` enthält die vollständige Serverkonfiguration für `lichtwelt.bartenbach.com`. Sie übernimmt:

- Weiterleitung der öffentlichen Startseite an den App-Container
- Verwaltung unter `/app/`
- IP-geschützte PDF-Auslieferung unter `/pdf/`
- Weiterleitung nicht erlaubter PDF-Aufrufe auf `/index.html`
- Ausgabe von `data/pdf-nicht-gefunden.html` bei fehlenden PDFs

Die bisherige Lichtwelt-Konfiguration im SWAG-Volume durch diese Konfiguration ersetzen. Es müssen keine HTML-Dateien mehr in das SWAG-Webroot kopiert werden. Anschließend die Nginx-Konfiguration testen und SWAG neu laden oder neu starten.

Wichtig: `PUBLIC_BASE_URL` muss exakt der von außen erreichbaren HTTPS-Adresse entsprechen. Diese Adresse wird in die QR-Codes geschrieben.

## Lokaler Entwicklungsstart

Die folgenden Befehle werden im Projektordner ausgeführt:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
APP_DATA_DIR=data PDF_STORAGE_DIR=data/pdf PUBLIC_BASE_URL=http://localhost:8000 python webapp.py
```

Unter Windows lautet die Aktivierung `.venv\\Scripts\\activate`. Umgebungsvariablen werden in PowerShell mit `$env:NAME="Wert"` gesetzt.

## Einstellungen

| Variable | Standard | Zweck |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | aktuelle Request-Adresse | Öffentliche Basisadresse für QR-Codes |
| `APP_USERNAME` / `APP_PASSWORD` | leer | Optionaler Schutz der Verwaltung |
| `MAX_UPLOAD_MB` | `50` | Maximale Upload-Größe |
| `APP_DATA_DIR` | `data` | Gemeinsame Ablage für öffentliche HTML-Dateien und PDFs |
| `PDF_STORAGE_DIR` | `<APP_DATA_DIR>/pdf` | Ablage der mobilen PDFs |
| `PDF_BRAND_LABEL` | `Bartenbach · Lichtkonzept` | Markenlabel im mobilen PDF |
| `PDF_WIDTH_MM` | `108` | Seitenbreite der mobilen PDF |
| `PDF_MARGIN_MM` | `15` | Seitenrand der mobilen PDF |

Gesundheitsprüfung: `GET /app/api/health`.
