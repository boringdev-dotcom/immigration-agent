# CEAC Visa Status Checker API Documentation

## Overview

This API provides endpoints to check U.S. visa application status from the CEAC (Consular Electronic Application Center) website. It handles Non-Immigrant Visa (NIV) applications and manages CAPTCHA challenges.

## Key Features

- Session-based browser automation using Playwright
- CAPTCHA image extraction for manual solving
- **Automatic CAPTCHA solving using ONNX model**
- Thread-safe session management with timeout
- Detailed status extraction including visa type, dates, and descriptions
- Popup/modal dialog handling for status display

## Requirements for Automatic CAPTCHA Solving

To use automatic CAPTCHA solving, you need:
1. The ONNX model file (`captcha.onnx`) in the project root
2. Required Python packages: `onnxruntime`, `Pillow`, `numpy`

## API Endpoints

### 1. Health Check

**GET** `/api/health`

Check if the service is running and get active session count.

**Response:**
```json
{
    "status": "healthy",
    "service": "visa-status-checker",
    "active_sessions": 0
}
```

### 2. Start Visa Status Check (Manual CAPTCHA)

**POST** `/api/visa-status/start`

Start a new visa status check session. This will navigate to the CEAC website, fill the form, and return a CAPTCHA image.

**Request Body:**
```json
{
    "location": "CHINA, BEIJING",
    "application_id": "AA0020AKAX",
    "passport_number": "EA1234567",
    "surname": "SMITH"
}
```

**Parameters:**
- `location`: Embassy/Consulate location (must match exactly as shown in the dropdown)
- `application_id`: Your visa application ID or case number
- `passport_number`: Your passport number
- `surname`: Your surname (full surname, not just first 5 letters)

**Response:**
```json
{
    "success": true,
    "session_id": "123e4567-e89b-12d3-a456-426614174000",
    "captcha_image": "base64_encoded_image_data",
    "message": "Please solve the CAPTCHA and submit using /api/visa-status/submit endpoint with the session_id"
}
```

### 3. Submit CAPTCHA Solution

**POST** `/api/visa-status/submit`

Submit the CAPTCHA solution to get the visa status.

**Request Body:**
```json
{
    "session_id": "123e4567-e89b-12d3-a456-426614174000",
    "captcha_solution": "ABC123"
}
```

**Success Response:**
```json
{
    "success": true,
    "data": {
        "status": "Application Received",
        "case_number": "AA0020AKAX",
        "case_created": "01-JAN-2024",
        "case_last_updated": "15-JAN-2024",
        "description": "Your case is open and ready for your interview..."
    },
    "screenshot": "base64_encoded_screenshot"
}
```

### 4. Check Visa Status with Automatic CAPTCHA Solving 🆕

**POST** `/api/visa-status/check-auto`

Perform a complete visa status check with automatic CAPTCHA solving using ONNX model.

**Request Body:**
```json
{
    "location": "NEPAL, KATHMANDU",
    "application_id": "AA00EILA2X",
    "passport_number": "PA123462",
    "surname": "SHARMA",
    "max_retries": 3
}
```

**Parameters:**
- `location`: Embassy/Consulate location
- `application_id`: Your visa application ID or case number
- `passport_number`: Your passport number
- `surname`: Your surname
- `max_retries`: (Optional) Maximum number of CAPTCHA retry attempts (default: 3)

**Success Response:**
```json
{
    "success": true,
    "data": {
        "status": "Application Received",
        "case_number": "AA00EILA2X",
        "case_created": "08-Jul-2025",
        "case_last_updated": "08-Jul-2025",
        "description": "Your case is open and ready for your interview..."
    },
    "screenshot": "base64_encoded_screenshot"
}
```

**Error Response (No ONNX Model):**
```json
{
    "success": false,
    "error": "Automatic CAPTCHA solving not available. ONNX model not loaded."
}
```

### 5. Cancel Session

**POST** `/api/visa-status/cancel`

Cancel an active session and close the browser.

**Request Body:**
```json
{
    "session_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

### 6. List Active Sessions (Debug)

**GET** `/api/visa-status/sessions`

List all active sessions (for debugging purposes).

### 7. All-in-One Check (Manual CAPTCHA)

**POST** `/api/visa-status/check`

Perform a complete visa status check in one request (if you already have the CAPTCHA solution).

## Important Notes

1. **Session Timeout**: Sessions expire after 5 minutes of inactivity
2. **Browser Mode**: Currently runs in headless mode. Set `headless=False` in code for debugging
3. **Location Format**: The location must match exactly as shown in the CEAC dropdown (e.g., "CHINA, BEIJING")
4. **CAPTCHA**: 
   - Manual endpoints return CAPTCHA images that must be solved manually
   - Automatic endpoint (`/check-auto`) requires the ONNX model file
   - The system will retry up to `max_retries` times if CAPTCHA fails
5. **Popup Handling**: The API automatically detects and extracts information from popup dialogs

## Example Usage

### Manual CAPTCHA Solving
```python
import requests
import base64

# Start a new check
response = requests.post('http://localhost:5000/api/visa-status/start', json={
    'location': 'CHINA, BEIJING',
    'application_id': 'AA0020AKAX',
    'passport_number': 'EA1234567',
    'surname': 'SMITH'
})

data = response.json()
session_id = data['session_id']

# Save and solve CAPTCHA
captcha_image = base64.b64decode(data['captcha_image'])
# ... solve CAPTCHA manually or with OCR ...

# Submit solution
response = requests.post('http://localhost:5000/api/visa-status/submit', json={
    'session_id': session_id,
    'captcha_solution': 'ABC123'
})

result = response.json()
if result['success']:
    print(f"Visa Status: {result['data']['status']}")
```

### Automatic CAPTCHA Solving
```python
import requests

# Check status with automatic CAPTCHA solving
response = requests.post('http://localhost:5000/api/visa-status/check-auto', json={
    'location': 'NEPAL, KATHMANDU',
    'application_id': 'AA00EILA2X',
    'passport_number': 'PA123456',
    'surname': 'SHARMA',
    'max_retries': 3
})

result = response.json()
if result['success']:
    print(f"Visa Status: {result['data']['status']}")
    print(f"Last Updated: {result['data']['case_last_updated']}")
```

## Setting Up ONNX Model

1. Download or obtain the `captcha.onnx` model file
2. Place it in the project root directory (same level as `src/`)
3. The API will automatically detect and use it

If the model is not found, the automatic endpoint will return an error and you'll need to use the manual endpoints.

## Future Improvements

1. ~~Integrate ONNX model for automatic CAPTCHA solving~~ ✅
2. Add support for Immigrant Visa (IV) applications
3. Implement webhook notifications for status changes
4. Add rate limiting and authentication
5. Support for batch checking multiple applications
6. Add CAPTCHA model training pipeline 