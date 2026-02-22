import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()
API_URL = "http://127.0.0.1:8000"
API_SECRET = os.getenv("API_SECRET")

def params():
    return {"x-api-key": API_SECRET}

def test_arming_logic():
    print("🧪 Testing Arming Logic...")
    
    # 1. Disarm System
    requests.post(f"{API_URL}/disarm", headers=params())
    
    # 2. Try Upload (Should Fail)
    print("   Attempting upload while DISARMED...")
    res = requests.post(f"{API_URL}/upload", 
        data={"content": "Should Fail", "type": "text"},
        headers=params()
    )
    if res.status_code == 403:
        print("   ✅ Correctly Rejected (403 Forbidden)")
    else:
        print(f"   ❌ FAILED: Status {res.status_code}")
        return

    # 3. Arm System
    print("   Arming System...")
    requests.post(f"{API_URL}/arm", headers=params())

    # 4. Try Upload (Should Succeed)
    print("   Attempting upload while ARMED...")
    res = requests.post(f"{API_URL}/upload", 
        data={"content": "Should Succeed", "type": "text"},
        headers=params()
    )
    if res.status_code == 200:
        print("   ✅ Upload Accepted (200 OK)")
    else:
        print(f"   ❌ FAILED: Status {res.status_code}")
        return

    # 5. Try Upload Again (Should Fail - One Shot)
    print("   Attempting immediate 2nd upload (Should Fail)...")
    res = requests.post(f"{API_URL}/upload", 
        data={"content": "Should Fail 2", "type": "text"},
        headers=params()
    )
    if res.status_code == 403:
        print("   ✅ One-Shot Logic Working (System Auto-Disarmed)")
    else:
        print(f"   ❌ FAILED: Status {res.status_code}")

if __name__ == "__main__":
    try:
        test_arming_logic()
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        print("Make sure server is running!")
