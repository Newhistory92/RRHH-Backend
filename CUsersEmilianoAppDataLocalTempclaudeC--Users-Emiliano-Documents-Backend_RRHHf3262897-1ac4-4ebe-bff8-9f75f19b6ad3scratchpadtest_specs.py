import requests
import json
import time

BASE_URL = "http://localhost:8000"

# First, we need to get an admin token
# Let's try a login (this might fail if no test user, but let's see)
print("Testing specsJson persistence in activos endpoints...")

# Get login token - try with admin credentials
login_data = {
    "username": "admin",
    "password": "admin123"
}

try:
    login_resp = requests.post(f"{BASE_URL}/auth/login", data=login_data)
    print(f"Login response: {login_resp.status_code}")
    if login_resp.status_code == 200:
        token = login_resp.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}
        print(f"✓ Got auth token")
    else:
        print(f"Login failed: {login_resp.text}")
        headers = {}
except Exception as e:
    print(f"Error during login: {e}")
    headers = {}

# Test 1: POST /activos with specsJson
print("\n[Test 1] POST /activos con specsJson")
post_data = {
    "numeroInventario": "TEST-SPECS-001",
    "nombre": "Test Asset with Specs",
    "categoriaId": 1,
    "fechaAlta": "2026-01-01",
    "specsJson": '{"core_count": 8, "boost_clock": 4.5}'
}

try:
    resp = requests.post(f"{BASE_URL}/activos", json=post_data, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        test1_id = resp.json().get("id")
        print(f"✓ Created asset with id: {test1_id}")
    else:
        print(f"Failed: {resp.text}")
except Exception as e:
    print(f"Error: {e}")

# Test 2: POST /activos WITHOUT specsJson
print("\n[Test 2] POST /activos sin specsJson")
post_data_no_specs = {
    "numeroInventario": "TEST-SPECS-002",
    "nombre": "Test Asset without Specs",
    "categoriaId": 1,
    "fechaAlta": "2026-01-01"
}

try:
    resp = requests.post(f"{BASE_URL}/activos", json=post_data_no_specs, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        test2_id = resp.json().get("id")
        print(f"✓ Created asset with id: {test2_id}")
    else:
        print(f"Failed: {resp.text}")
except Exception as e:
    print(f"Error: {e}")

# Test 3: PUT /activos with updated specsJson
print("\n[Test 3] PUT /activos con specsJson actualizado")
if 'test1_id' in locals():
    put_data = {
        "numeroInventario": "TEST-SPECS-001",
        "nombre": "Test Asset with Updated Specs",
        "categoriaId": 1,
        "fechaAlta": "2026-01-01",
        "specsJson": '{"core_count": 16, "boost_clock": 5.0}'
    }
    try:
        resp = requests.put(f"{BASE_URL}/activos/{test1_id}", json=put_data, headers=headers)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print(f"✓ Updated asset {test1_id}")
        else:
            print(f"Failed: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

print("\n[Info] Test data created. Check DB directly to verify values.")
