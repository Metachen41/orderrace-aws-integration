import requests
import json
import os

# --- KONFIGURATION (Bitte anpassen!) ---
# Trage hier deine API-Gateway-URL ein, die du aus dem SAM Deploy Output ("ApiUrl") erhältst:
API_URL = os.environ.get("API_URL", "https://YOUR_API_ID.execute-api.eu-central-1.amazonaws.com/Prod")
TOKEN = os.environ.get("API_TOKEN", "YOUR_SECRET_TOKEN")

ORDER_ID = "11000199"
ORDER_RACE_FILENAME = f"muku#DE-74078-Heilbronn#NEU#{ORDER_ID}#Beispiel-Datei.pdf"

def create_dummy_pdf():
    """Erstellt ein minimalistisches PDF zu Testzwecken."""
    content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n4 0 obj\n<< /Length 51 >>\nstream\nBT\n/F1 24 Tf\n100 700 Td\n(Testdokument von OrderRace) Tj\nET\nendstream\nendobj\n5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000222 00000 n \n0000000323 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n412\n%%EOF"
    pdf_path = "dummy_document.pdf"
    with open(pdf_path, 'wb') as f:
        f.write(content)
    return pdf_path

def test_ingest_document():
    if API_URL == "HIER_API_URL_EINTRAGEN":
        print("FEHLER: Bitte erst API_URL im Skript eintragen!")
        return

    print(f"--- STARTE TEST: Senden von Dokument an {API_URL}/ingest ---")
    
    url = f"{API_URL}/ingest?typ=document"
    
    pdf_path = create_dummy_pdf()
        
    with open(pdf_path, 'rb') as f:
        pdf_content = f.read()

    files = {
        'file': (ORDER_RACE_FILENAME, pdf_content, 'application/pdf')
    }
    
    data = {
        'doc_type_1': 'ZOLL'
    }
    headers = {
        'Authorization': f'Bearer {TOKEN}'
    }

    try:
        response = requests.post(url, data=data, files=files, headers=headers)
        
        print(f"Status Code: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
        
        if response.status_code == 200:
            print(f"\nERFOLG! PDF wurde gesendet und in DynamoDB ({ORDER_ID}) ergänzt.")
        else:
            print("\nFEHLER beim Senden des PDFs.")
            
    except Exception as e:
        print(f"Exception aufgetreten: {e}")
    finally:
        # Räume das temporäre Dummy-PDF auf
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

if __name__ == "__main__":
    test_ingest_document()
