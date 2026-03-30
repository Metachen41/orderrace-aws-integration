import os
import sys
import re
import json
import logging
import requests
from pathlib import Path

# --- KONFIGURATION ---
API_BASE_URL = os.environ.get("API_BASE_URL", "https://YOUR_API_ID.execute-api.eu-central-1.amazonaws.com/Prod")
API_KEY = os.environ.get("API_KEY", "")

LBASE_SDG_DIR = os.environ.get("LBASE_SDG_DIR", r"C:\Lbase\Import\SDG")
LBASE_SDG_UPDATE_DIR = os.environ.get("LBASE_SDG_UPDATE_DIR", r"C:\Lbase\Import\SDG_UPDATE")
LBASE_DOC_DIR = os.environ.get("LBASE_DOC_DIR", r"C:\Lbase\Import\DOCS")
LBASE_ORDERAUTO_DIR = os.environ.get("LBASE_ORDERAUTO_DIR", r"C:\Lbase\Import\ORDERAUTO")

_VERSION_PATTERN = re.compile(r'_v\d+\.sdg$')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("poller.log", encoding="utf-8"),
    ],
)


def ensure_directories():
    for d in (LBASE_SDG_DIR, LBASE_SDG_UPDATE_DIR, LBASE_DOC_DIR, LBASE_ORDERAUTO_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)


def resolve_target_dir(file_key, order_id):
    """Routes an S3 file key to the correct local directory, grouped by order_id."""
    filename = file_key.split('/')[-1]

    if file_key.startswith('sdg/'):
        base = LBASE_SDG_UPDATE_DIR if _VERSION_PATTERN.search(filename) else LBASE_SDG_DIR
        return os.path.join(base, order_id), filename

    if file_key.startswith('docs/'):
        return os.path.join(LBASE_DOC_DIR, order_id), filename

    if file_key.startswith('orderauto/'):
        return os.path.join(LBASE_ORDERAUTO_DIR, order_id), filename

    return os.path.join(LBASE_DOC_DIR, order_id), filename


def fetch_pending_orders():
    logging.info(f"Frage neue Auftraege ab von {API_BASE_URL}/pull")
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    try:
        response = requests.get(f"{API_BASE_URL}/pull", headers=headers, timeout=10)
        response.raise_for_status()
        return response.json().get("items", [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Fehler beim Abruf von /pull: {e}")
        return []


def download_file(url, target_path):
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Download fehlgeschlagen fuer {url}: {e}")
        return False
    except IOError as e:
        logging.error(f"Schreibfehler auf lokales Laufwerk ({target_path}): {e}")
        return False


def acknowledge_files(processed_map):
    if not processed_map:
        return
    logging.info("Sende Acknowledge fuer Dateien")
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    payload = {"processed_files": processed_map}
    try:
        response = requests.post(f"{API_BASE_URL}/pull/ack", json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logging.info("Acknowledge erfolgreich.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Fehler beim Senden von /pull/ack: {e}")


def main():
    ensure_directories()

    items = fetch_pending_orders()
    if not items:
        logging.info("Keine neuen Auftraege gefunden.")
        return

    logging.info(f"{len(items)} Auftraege zur Verarbeitung gefunden.")

    successful_files = {}

    for item in items:
        order_id = item.get("order_id")
        downloads = item.get("downloads", [])

        if not downloads:
            continue

        logging.info(f"Verarbeite OrderID: {order_id} ({len(downloads)} Dateien)")

        success_for_this_order = []

        for download in downloads:
            file_key = download.get("file_key", "")
            url = download.get("url", "")

            target_dir, filename = resolve_target_dir(file_key, order_id)
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            target_path = os.path.join(target_dir, filename)

            logging.info(f"  Lade herunter: {filename} -> {target_path}")

            if download_file(url, target_path):
                success_for_this_order.append(file_key)
            else:
                logging.warning(f"  Fehler beim Download von {file_key}")

        if success_for_this_order:
            successful_files[order_id] = success_for_this_order

    if successful_files:
        acknowledge_files(successful_files)


if __name__ == "__main__":
    main()
