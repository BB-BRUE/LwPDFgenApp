# LwPDFgenApp

LwPDFgenApp stellt eine Weboberfläche bereit, mit der PDF-Dateien hochgeladen, für Smartphones optimiert und zusammen mit einem QR-Code veröffentlicht werden können. Für die Installation auf dem Linux-Webserver genügt der vollständige Projektordner `LwPDFgenApp`.

## Funktionen und URLs

- `/` und `/index.html`: öffentliche, zweisprachige Lichtwelt-Startseite
- `/app/`: PDF-Verwaltung mit Upload, Liste, QR-Download und Löschen
- `/pdf/<datei>.pdf`: Auslieferung einer erzeugten mobilen PDF
- `/app/api/health`: Gesundheitsprüfung
- optionaler HTTP-Basisschutz für die Verwaltung
- QR-Codes im Bartenbach-Design mit schwarzem Codemuster und originalem Bartenbach-Punktlogo

Die Anwendung selbst verlangt für `/pdf/...` keine Anmeldung, damit QR-Links auf Smartphones funktionieren. Die mitgelieferte SWAG-Konfiguration schränkt diese URLs zusätzlich auf die dort eingetragenen Quell-IP-Adressen ein.

## Gemeinsames Datenverzeichnis

Es gibt nur einen persistenten Bind-Mount: Das Host-Verzeichnis `data` wird als `/app/data` in den Container eingebunden.

```text
data/
├── index.html
├── pdf-nicht-gefunden.html
├── bartenbach-logo.png
├── wifi-lw-internet-qr.png
└── pdf/
    ├── .tmp/
    └── *.pdf
```

- `data/index.html` ist die öffentliche Startseite.
- `data/pdf-nicht-gefunden.html` wird bei fehlenden PDFs angezeigt.
- `data/bartenbach-logo.png` ist das auf der Startseite verwendete Logo.
- `data/wifi-lw-internet-qr.png` verbindet mit dem WLAN `LW-Internet` und dem Passwort `LW2015Ald`.
- `data/pdf` enthält temporäre Dateien und die erzeugten mobilen PDFs.

Beim Containerstart gilt:

- Fehlt `data/index.html`, wird `static/index.example.html` dorthin kopiert.
- Fehlt `data/pdf-nicht-gefunden.html`, wird die Standard-Fehlerseite kopiert.
- Logo und WLAN-QR-Code werden bei jedem Start aus dem aktuellen Image aktualisiert.
- Vorhandene HTML-Dateien werden nicht überschrieben.

Die Beispiel-Startseite ist responsiv und enthält deutsche sowie englische Texte. Logo und QR-Code werden als echte PNG-Dateien über `/site-assets/` ausgeliefert; sie sind nicht als Base64 im HTML eingebettet.

Ein separates Webroot im SWAG-Verzeichnis, beispielsweise `/config/www/lichtwelt`, wird nicht mehr benötigt.

## Installation mit Docker Compose

### 1. Konfiguration vorbereiten

```bash
cp .env.example .env
mkdir -p data/pdf
```

In `.env` mindestens die öffentliche Adresse und ein starkes Passwort setzen:

```dotenv
PUBLIC_BASE_URL=https://lichtwelt.bartenbach.com
APP_USERNAME=admin
APP_PASSWORD=ein-langes-zufaelliges-passwort
SWAG_NETWORK=swag_proxy-net
APP_UID=1000
APP_GID=1000
```

`APP_USERNAME` und `APP_PASSWORD` müssen entweder beide gesetzt oder beide leer sein.

Falls eine bestehende öffentliche Startseite übernommen werden soll, muss sie vor dem ersten Start nach `data/index.html` kopiert werden:

```bash
cp /pfad/zur/bisherigen/index.html data/index.html
```

Für die mitgelieferte Beispielseite ist kein manueller Kopiervorgang nötig.

### 2. SWAG-Netz prüfen

Das externe Docker-Netz heißt standardmäßig `swag_proxy-net`:

```bash
docker network inspect swag_proxy-net
```

Hat das Netz einen anderen Namen, muss `SWAG_NETWORK` in `.env` entsprechend geändert werden.

### 3. Anwendung bauen und starten

```bash
docker compose up -d --build
```

Der Anwendungscontainer veröffentlicht absichtlich keinen Host-Port und ist nur im gemeinsamen SWAG-Netz erreichbar.

Status und Logs prüfen:

```bash
docker compose ps
docker compose logs --tail=100 lwpdfgen
```

## Dateirechte und Benutzer

Ein Host-Benutzer mit dem Namen `lwpdfgen` allein löst Bind-Mount-Berechtigungen nicht zuverlässig. Linux vergleicht bei Dateirechten die numerische UID und GID, nicht den Benutzernamen.

Der Container-Benutzer `lwpdfgen` wird standardmäßig mit UID/GID `1000:1000` gebaut. Andere Werte können über `APP_UID` und `APP_GID` in `.env` gesetzt werden.

Der Container startet nur zur Initialisierung mit Root-Rechten. Der Entry-Point:

1. legt `/app/data/pdf/.tmp` an,
2. setzt `lwpdfgen` als Eigentümer der benötigten Verzeichnisse und Dateien,
3. wechselt auf die konfigurierte UID/GID,
4. startet Gunicorn als unprivilegierter Benutzer.

Auf einem normalen lokalen Linux-Dateisystem ist deshalb kein zusätzlicher Host-Benutzer und kein `chmod 777` erforderlich. Bei NFS-, Rootless- oder anderen Dateisystemen, die `chown` verhindern, muss das Host-Verzeichnis vorab numerisch der konfigurierten UID/GID zugeordnet werden.

## Startseite und WLAN-QR-Code

Die Vorlage liegt in `static/index.example.html`. Sie verwendet:

- `static/bartenbach_lighting innovators.png` als Logoquelle,
- `static/wifi-lw-internet-qr.png` als WLAN-QR-Code,
- Deutsch und Englisch,
- die Markenfarben Orange `RGB 250/150/30` (`#FA961E`) und Dunkel `#1A171B`.

Der WLAN-QR-Code enthält:

```text
WIFI:T:WPA;S:LW-Internet;P:LW2015Ald;;
```

Soll eine bereits vorhandene `data/index.html` durch die Beispielseite ersetzt werden:

```bash
cp static/index.example.html data/index.html
docker compose restart lwpdfgen
```

## QR-Codes für PDFs

Der QR-Download unter `/app/` wird zentral von `mobile_pdf_pipeline.py` erzeugt. Jeder QR-Code verwendet:

- Fehlerkorrekturstufe `H`,
- schwarze QR-Module auf weißem Grund,
- einen weißen Sicherheitsabstand,
- das originale Bartenbach-Punktlogo aus `static/dot_bartenbach.png` in der Mitte.

Nach Änderungen an der QR-Erzeugung muss das Image neu gebaut werden:

```bash
docker compose up -d --build
```

## SWAG-Proxy

Es stehen zwei vollständige Beispielkonfigurationen zur Auswahl:

- `deploy/swag/lichtwelt.subdomain.conf.example`: kompakter Proxy mit PDF-Zugriff nur für die darin freigegebenen Quell-IP-Adressen.
- `deploy/swag/lichtwelt-public.subdomain.conf.example`: kompakter Einzel-Proxy ohne IP-Einschränkung; jede Person mit dem Link kann die PDF abrufen.

Beide Varianten übernehmen:

- Weiterleitung der Startseite an den App-Container,
- Auslieferung von Logo und WLAN-QR-Code über `/site-assets/`,
- Verwaltung unter `/app/`,
- PDF-Auslieferung unter `/pdf/`,
- Ausgabe von `data/pdf-nicht-gefunden.html` bei fehlenden PDFs.

Nur die IP-geschützte Variante leitet nicht freigegebene PDF-Aufrufe auf `/index.html` weiter. Die öffentliche Variante enthält keine `allow`-, `deny`- oder IP-bezogenen `error_page`-Regeln.

Die gewünschte Variante als aktive Lichtwelt-Konfiguration in das SWAG-Volume übernehmen. HTML- oder PNG-Dateien müssen nicht in das SWAG-Webroot kopiert werden.

Danach die Nginx-Konfiguration im SWAG-Container testen und SWAG neu laden beziehungsweise neu starten. Der konkrete Containername hängt von der SWAG-Installation ab, beispielsweise:

```bash
docker exec <swag-container> nginx -t
docker restart <swag-container>
```

`PUBLIC_BASE_URL` muss exakt der von außen erreichbaren HTTPS-Adresse entsprechen, da diese Adresse in die PDF-QR-Codes geschrieben wird.

## Aktualisierung

Nach Änderungen am Projekt:

```bash
docker compose up -d --build
docker compose logs --tail=100 lwpdfgen
```

Die persistenten PDFs und benutzerdefinierten HTML-Dateien in `data` bleiben erhalten. Die verwalteten Logo- und WLAN-QR-PNGs werden aus dem neuen Image aktualisiert.

## Lokaler Entwicklungsstart ohne Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data/pdf
cp static/index.example.html data/index.html
cp static/pdf-nicht-gefunden.html data/pdf-nicht-gefunden.html
cp "static/bartenbach_lighting innovators.png" data/bartenbach-logo.png
cp static/wifi-lw-internet-qr.png data/wifi-lw-internet-qr.png
APP_DATA_DIR=data PDF_STORAGE_DIR=data/pdf PUBLIC_BASE_URL=http://localhost:8000 python webapp.py
```

Unter Windows wird die virtuelle Umgebung mit `.venv\Scripts\activate` aktiviert. Umgebungsvariablen werden in PowerShell mit `$env:NAME="Wert"` gesetzt.

## Konfigurationsvariablen

### Von Docker Compose verwendet

| Variable | Standard | Zweck |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | erforderlich für produktive QR-Links | Öffentliche HTTPS-Basisadresse |
| `APP_USERNAME` / `APP_PASSWORD` | leer | Optionaler HTTP-Basisschutz der Verwaltung |
| `MAX_UPLOAD_MB` | `50` | Maximale Upload-Größe in MB |
| `PDF_BRAND_LOGO` | `/app/static/bartenbach_master.png` | Markenlogo im mobilen PDF |
| `SWAG_NETWORK` | `swag_proxy-net` | Name des externen SWAG-Netzes |
| `APP_UID` / `APP_GID` | `1000` | Numerische UID/GID des Container-Benutzers |

### Interne Pfade und weitere App-Optionen

| Variable | Standard ohne Docker | Docker-Compose-Wert | Zweck |
| --- | --- | --- | --- |
| `APP_DATA_DIR` | `data` | `/app/data` | Gemeinsame Ablage für HTML, PNGs und PDFs |
| `PDF_STORAGE_DIR` | `<APP_DATA_DIR>/pdf` | `/app/data/pdf` | Ablage der mobilen PDFs |
| `PDF_WIDTH_MM` | `108` | nicht explizit gesetzt | Seitenbreite der mobilen PDF |
| `PDF_MARGIN_MM` | `15` | nicht explizit gesetzt | Seitenrand der mobilen PDF |
| `PDF_FOOTER` | Standardtext der Anwendung | nicht explizit gesetzt | Fußzeile im mobilen PDF |

Gesundheitsprüfung: `GET /app/api/health`.
