import requests
import json
import os

# --- KONFIGURATION (Bitte anpassen!) ---
# Trage hier deine API-Gateway-URL ein, die du aus dem SAM Deploy Output ("ApiUrl") erhältst:
API_URL = "https://u2ovkcybvd.execute-api.eu-central-1.amazonaws.com/Prod"
# (Wir gehen davon aus, dass `/pull` vorerst ohne API Key erreichbar ist, oder ein Token nutzt)

def test_polling():
    if API_URL == "HIER_API_URL_EINTRAGEN":
        print("FEHLER: Bitte erst API_URL im Skript eintragen!")
        return

    print(f"--- STARTE TEST: Polling von offenen Datensätzen an {API_URL}/pull ---")
    
    url = f"{API_URL}/pull"
    
    try:
        print(f"Sende GET Request an {url}...")
        response = requests.get(url)
        
        print(f"\nStatus Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            print(f"Erfolgreich abgerufen! Es liegen {len(items)} Aufträge zur Abholung bereit.\n")
            
            for item in items:
                order_id = item.get("order_id")
                downloads = item.get("downloads", [])
                print(f"-> OrderID: {order_id}")
                for dl in downloads:
                    key = dl.get("file_key")
                    link = dl.get("url")
                    print(f"     File: {key}")
                    print(f"     Link: {link[:60]}... (gekürzt)")
                print("-" * 40)
        else:
            print("\nFEHLER beim Abruf der Polling-Daten.")
            print(response.text)
            
    except Exception as e:
        print(f"Exception aufgetreten: {e}")

if __name__ == "__main__":
    test_polling()
