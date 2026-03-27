import requests
import json
import os

# --- KONFIGURATION ---
API_URL = "https://u2ovkcybvd.execute-api.eu-central-1.amazonaws.com/Prod"
TOKEN = "VtljtFfPz9LmBO7L9yZEF807bckqo3zS"
TEST_JSON_PATH = "../docs/test.json"


def test_ingest_orderauto():
    """
    Sends a JSON as OrderAuto (?typ=orderauto).
    The backend should store it as raw JSON (no Fortras conversion).
    """
    if not os.path.exists(TEST_JSON_PATH):
        print(f"FEHLER: test.json nicht gefunden unter {TEST_JSON_PATH}")
        return

    with open(TEST_JSON_PATH, 'r', encoding='utf-8') as f:
        json_content = f.read()

    url = f"{API_URL}/ingest?typ=orderauto"
    headers = {'Authorization': f'Bearer {TOKEN}'}
    files = {'dfue_file': ('orderauto_data.json', json_content, 'application/json')}

    print(f"--- TEST: OrderAuto an {url} ---")

    try:
        response = requests.post(url, files=files, headers=headers)
        print(f"Status Code: {response.status_code}")
        body = response.json()
        print(json.dumps(body, indent=2))

        if response.status_code == 200:
            saved = body.get("saved_files", [])
            is_orderauto = any("orderauto/" in f for f in saved)
            if is_orderauto:
                print("\nERFOLG! OrderAuto als rohe JSON in S3 gespeichert.")
            else:
                print("\nWARNUNG: Kein orderauto/-Praefix in saved_files gefunden.")
        else:
            print("\nFEHLER beim Senden der OrderAuto-Daten.")
    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    test_ingest_orderauto()
