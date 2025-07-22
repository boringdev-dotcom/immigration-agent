import requests
import json
import time

# Base URL for the API
BASE_URL = "http://localhost:5000"

def test_health():
    """Test the health check endpoint"""
    print("Testing health check...")
    response = requests.get(f"{BASE_URL}/api/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print()

def test_visa_status_start():
    """Test starting a visa status check"""
    print("Testing visa status start...")
    
    # Test data - you'll need to provide real values
    data = {
        "location": "NEPAL, KATHMANDU",  # Example location
        "application_id": "AA00EILA2X",  # Example case number
        "passport_number": "PA123456",  # Example passport
        "surname": "SHARMA"  # Example surname
    }
    
    response = requests.post(f"{BASE_URL}/api/visa-status/start", json=data)
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Response: {json.dumps(result, indent=2)}")
    
    if result.get('success') and result.get('session_id'):
        print(f"\nSession ID: {result['session_id']}")
        print("CAPTCHA image received. Please solve the CAPTCHA manually.")
        
        # Save CAPTCHA image for viewing
        if result.get('captcha_image'):
            import base64
            captcha_data = base64.b64decode(result['captcha_image'])
            with open('captcha.png', 'wb') as f:
                f.write(captcha_data)
            print("CAPTCHA saved as captcha.png")
            
        return result['session_id']
    
    return None

def test_visa_status_submit(session_id, captcha_solution):
    """Test submitting the CAPTCHA solution"""
    print(f"\nTesting visa status submit with session {session_id}...")
    
    data = {
        "session_id": session_id,
        "captcha_solution": captcha_solution
    }
    
    response = requests.post(f"{BASE_URL}/api/visa-status/submit", json=data)
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Response: {json.dumps(result, indent=2)}")
    
    if result.get('success') and result.get('screenshot'):
        # Save screenshot
        import base64
        screenshot_data = base64.b64decode(result['screenshot'])
        with open('result_screenshot.png', 'wb') as f:
            f.write(screenshot_data)
        print("Result screenshot saved as result_screenshot.png")

def test_auto_captcha():
    """Test the automatic CAPTCHA solving endpoint"""
    print("Testing automatic CAPTCHA solving...")
    
    # Test data
    data = {
        "location": "NEPAL, KATHMANDU",
        "application_id": "AA00EILA2X",
        "passport_number": "PA123456",
        "surname": "SHARMA",
        "max_retries": 3  # Try up to 3 times if CAPTCHA fails
    }
    
    print(f"Sending request with data: {json.dumps(data, indent=2)}")
    
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/api/visa-status/check-auto", json=data)
    end_time = time.time()
    
    print(f"\nRequest completed in {end_time - start_time:.2f} seconds")
    print(f"Status: {response.status_code}")
    
    result = response.json()
    print(f"Response: {json.dumps(result, indent=2)}")
    
    if result.get('success'):
        print("\n✅ SUCCESS! Visa status retrieved automatically:")
        if 'data' in result:
            for key, value in result['data'].items():
                print(f"  {key}: {value}")
        
        # Save screenshot if available
        if result.get('screenshot'):
            import base64
            screenshot_data = base64.b64decode(result['screenshot'])
            with open('auto_result_screenshot.png', 'wb') as f:
                f.write(screenshot_data)
            print("\nScreenshot saved as auto_result_screenshot.png")
    else:
        print(f"\n❌ FAILED: {result.get('error', 'Unknown error')}")

def test_manual_flow():
    """Test the manual CAPTCHA flow"""
    print("=== Testing Manual CAPTCHA Flow ===\n")
    
    # Start the process
    session_id = test_visa_status_start()
    
    if session_id:
        # Wait for user to solve CAPTCHA
        captcha_solution = input("\nPlease enter the CAPTCHA solution: ")
        
        # Submit the solution
        test_visa_status_submit(session_id, captcha_solution)
    else:
        print("Failed to start visa status check")

def test_all_in_one():
    """Test the all-in-one endpoint with manual CAPTCHA"""
    print("\n=== Testing All-in-One Endpoint ===")
    
    data = {
        "location": "NEPAL, KATHMANDU",
        "application_id": "AA00EILA2X",
        "passport_number": "PA123456",
        "surname": "SHARMA"
        # No captcha_solution provided, so it should return the CAPTCHA image
    }
    
    response = requests.post(f"{BASE_URL}/api/visa-status/check", json=data)
    result = response.json()
    
    if result.get('captcha_required'):
        print("CAPTCHA required. Saving image...")
        if result.get('captcha_image'):
            import base64
            captcha_data = base64.b64decode(result['captcha_image'])
            with open('captcha_allinone.png', 'wb') as f:
                f.write(captcha_data)
            print("CAPTCHA saved as captcha_allinone.png")
            
        # Now submit with CAPTCHA solution
        captcha_solution = input("\nPlease enter the CAPTCHA solution: ")
        data['captcha_solution'] = captcha_solution
        
        response = requests.post(f"{BASE_URL}/api/visa-status/check", json=data)
        result = response.json()
        print(f"\nFinal result: {json.dumps(result, indent=2)}")

def main():
    """Main test function with menu"""
    print("=== Visa Status API Test Suite ===\n")
    
    # Always test health first
    test_health()
    
    print("\nSelect test to run:")
    print("1. Test manual CAPTCHA flow (start -> submit)")
    print("2. Test automatic CAPTCHA solving")
    print("3. Test all-in-one endpoint")
    print("4. Run all tests")
    
    choice = input("\nEnter choice (1-4): ")
    
    if choice == "1":
        test_manual_flow()
    elif choice == "2":
        test_auto_captcha()
    elif choice == "3":
        test_all_in_one()
    elif choice == "4":
        print("\n" + "="*50)
        test_manual_flow()
        print("\n" + "="*50)
        test_auto_captcha()
        print("\n" + "="*50)
        test_all_in_one()
    else:
        print("Invalid choice")

if __name__ == "__main__":
    main() 