import requests
import json
import os

# --- KONFIGURATION ---
API_URL = os.environ.get("API_URL", "https://YOUR_API_ID.execute-api.eu-central-1.amazonaws.com/Prod")
TOKEN = os.environ.get("API_TOKEN", "YOUR_SECRET_TOKEN")
TEST_JSON_PATH = "../docs/test.json"


def test_ingest_audit():
    """
    Sends the same order twice with ?typ=audit.
    The first call should produce _v1.sdg, the second _v2.sdg.
    """
    if not os.path.exists(TEST_JSON_PATH):
        print(f"FEHLER: test.json nicht gefunden unter {TEST_JSON_PATH}")
        return

    with open(TEST_JSON_PATH, 'r', encoding='utf-8') as f:
        json_content = f.read()

    try:
        parsed_json = json.loads(json_content)
        onum = parsed_json["orders"][0]["onum"]
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"FEHLER: onum konnte nicht gelesen werden: {exc}")
        return

    url = f"{API_URL}/ingest?typ=audit"
    headers = {'Authorization': f'Bearer {TOKEN}'}

    for run in (1, 2):
        print(f"\n--- TEST: Audit Run {run} fuer onum={onum} ---")
        files = {'file': ('audit_auftrag.json', json_content, 'application/json')}

        try:
            response = requests.post(url, files=files, headers=headers)
            print(f"Status Code: {response.status_code}")
            body = response.json()
            print(json.dumps(body, indent=2))

            if response.status_code == 200:
                saved = body.get("saved_files", [])
                expected_suffix = f"_v{run}.sdg"
                has_version = any(expected_suffix in f for f in saved)
                if has_version:
                    print(f"ERFOLG! Audit-Version {run} korrekt erzeugt.")
                else:
                    print(f"WARNUNG: Erwartet *{expected_suffix} in saved_files, aber nicht gefunden.")
            else:
                print(f"FEHLER bei Audit Run {run}.")
        except Exception as e:
            print(f"Exception: {e}")


if __name__ == "__main__":
    test_ingest_audit()
