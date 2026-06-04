import requests

def test_saldos():
    url = "http://localhost:8000/licenses/saldos?employee_id=8"
    try:
        response = requests.get(url)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_saldos()
