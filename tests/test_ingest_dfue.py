import requests
import json
import os

# --- KONFIGURATION ---
API_URL = "https://u2ovkcybvd.execute-api.eu-central-1.amazonaws.com/Prod"
TOKEN = "VtljtFfPz9LmBO7L9yZEF807bckqo3zS"
TEST_JSON_PATH = "../docs/test.json"


def test_ingest_dfue():
    print(f"--- TEST: DFUE mit ?typ=dfue an {API_URL}/ingest ---")

    if not os.path.exists(TEST_JSON_PATH):
        print(f"FEHLER: test.json nicht gefunden unter {TEST_JSON_PATH}")
        return

    with open(TEST_JSON_PATH, 'r', encoding='utf-8') as f:
        json_content = f.read()

    try:
        parsed_json = json.loads(json_content)
        onums = [o["onum"] for o in parsed_json.get("orders", [])]
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"FEHLER: onum konnte nicht gelesen werden: {exc}")
        return

    url = f"{API_URL}/ingest?typ=dfue"
    files = {'dfue_file': ('auftrag.json', json_content, 'application/json')}
    headers = {'Authorization': f'Bearer {TOKEN}'}

    try:
        response = requests.post(url, files=files, headers=headers)
        print(f"Status Code: {response.status_code}")
        print(json.dumps(response.json(), indent=2))

        if response.status_code == 200:
            print(f"\nERFOLG! DFUE fuer onums {onums} verarbeitet.")
        else:
            print("\nFEHLER beim Senden der DFUE.")
    except Exception as e:
        print(f"Exception: {e}")


def test_ingest_dfue_multi_order():
    """Sends a JSON with 2 orders to test multi-order splitting."""
    print(f"\n--- TEST: Multi-Order DFUE mit 2 Auftraegen ---")

    if not os.path.exists(TEST_JSON_PATH):
        print(f"FEHLER: test.json nicht gefunden unter {TEST_JSON_PATH}")
        return

    with open(TEST_JSON_PATH, 'r', encoding='utf-8') as f:
        parsed_json = json.load(f)

    original_order = parsed_json["orders"][0]
    second_order = json.loads(json.dumps(original_order))
    second_order["onum"] = str(int(original_order["onum"]) + 1)

    multi_json = {
        "header": parsed_json["header"],
        "orders": [original_order, second_order],
        "trailer": {"count": "2"},
    }

    url = f"{API_URL}/ingest?typ=dfue"
    json_content = json.dumps(multi_json, ensure_ascii=False)
    files = {'dfue_file': ('multi_auftrag.json', json_content, 'application/json')}
    headers = {'Authorization': f'Bearer {TOKEN}'}

    try:
        response = requests.post(url, files=files, headers=headers)
        print(f"Status Code: {response.status_code}")
        print(json.dumps(response.json(), indent=2))

        if response.status_code == 200:
            print(f"\nERFOLG! Multi-Order DFUE verarbeitet.")
        else:
            print("\nFEHLER beim Senden der Multi-Order DFUE.")
    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    test_ingest_dfue()
    test_ingest_dfue_multi_order()
