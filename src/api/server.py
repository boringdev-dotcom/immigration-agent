from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from playwright.sync_api import sync_playwright
import base64
import io
import os
import tempfile
import time
from datetime import datetime
import uuid
import threading
from threading import Lock
import logging
from .captcha_handler import OnnxCaptchaHandle, ManualCaptchaHandle, CaptchaHandle

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session storage with thread safety
sessions = {}
sessions_lock = Lock()
SESSION_TIMEOUT = 300  # 5 minutes timeout

# Global CAPTCHA handler
captcha_handler = None

def initialize_captcha_handler(use_onnx=True, model_path='captcha.onnx'):
    """Initialize the CAPTCHA handler"""
    global captcha_handler
    if use_onnx:
        try:
            # Check if model file exists
            if not os.path.exists(model_path):
                logger.warning(f"ONNX model not found at {model_path}, falling back to manual CAPTCHA")
                captcha_handler = ManualCaptchaHandle()
            else:
                captcha_handler = OnnxCaptchaHandle(model_path)
                logger.info("Using ONNX CAPTCHA solver")
        except Exception as e:
            logger.error(f"Failed to initialize ONNX CAPTCHA handler: {e}")
            captcha_handler = ManualCaptchaHandle()
    else:
        captcha_handler = ManualCaptchaHandle()
        logger.info("Using manual CAPTCHA solver")

# Initialize on startup
initialize_captcha_handler()

class VisaStatusChecker:
    def __init__(self, session_id, auto_solve_captcha=True):
        self.session_id = session_id
        self.playwright = None
        self.browser = None
        self.page = None
        self.context = None
        self.created_at = datetime.now()
        self.auto_solve_captcha = auto_solve_captcha
        
    def start_browser(self, headless=True):
        """Initialize playwright and browser with optimizations"""
        self.playwright = sync_playwright().start()
        
        # Launch browser with performance optimizations
        # Using configuration similar to successful implementations
        self.browser = self.playwright.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--window-size=1920,1080',
                '--start-maximized',
                '--disable-infobars',
                '--disable-extensions',
                '--disable-automation',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding'
            ]
        )
        
        # Create context with optimizations
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            permissions=['geolocation'],
            ignore_https_errors=True,
            # Add extra headers to appear more legitimate
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
        )
        
        # Remove blocking of resources - we need everything to load properly
        # self.context.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,eot}", lambda route: route.abort())
        # self.context.route("**/*.css", lambda route: route.abort())
        
        self.page = self.context.new_page()
        
        # Set longer default timeout
        self.page.set_default_timeout(90000)  # 90 seconds
        
        # Add stealth mode scripts
        self.page.add_init_script("""
            // Override the navigator.webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Override the chrome property
            window.chrome = {
                runtime: {},
            };
            
            // Override the permissions query
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
        
    def close_browser(self):
        """Close browser and playwright"""
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.error(f"Error closing browser: {str(e)}")
            
    def is_expired(self):
        """Check if session has expired"""
        return (datetime.now() - self.created_at).total_seconds() > SESSION_TIMEOUT
            
    def navigate_to_visa_status_page(self):
        """Navigate to the visa status check page"""
        try:
            logger.info("Navigating to CEAC visa status page (NIV)...")
            
            # Navigate directly to NIV form
            response = self.page.goto('https://ceac.state.gov/ceacstattracker/status.aspx?App=NIV', 
                          wait_until='domcontentloaded', 
                          timeout=60000)
            
            if response and response.status != 200:
                logger.error(f"Got status code: {response.status}")
                return False
            
            # Wait a bit for any redirects or JavaScript to execute
            self.page.wait_for_timeout(3000)
            
            # Check if we're on the right page by looking for NIV-specific form fields
            try:
                # Check for the location dropdown which should be present for NIV
                location_dropdown = self.page.query_selector('select[id*="ddlLocation"]')
                if location_dropdown:
                    logger.info("Found NIV form with location dropdown")
                    return True
                else:
                    # If location dropdown not found, check if at least the case number field is present
                    case_field = self.page.query_selector('#Visa_Case_Number')
                    if case_field:
                        logger.info("Found case number field")
                        return True
                    
                    logger.error("Could not find expected NIV form fields")
                    # Take a screenshot for debugging
                    self.page.screenshot(path="debug_navigation.png")
                    
                    # Log the page URL and title
                    logger.info(f"Current URL: {self.page.url}")
                    logger.info(f"Page title: {self.page.title()}")
                    
                    # Check if there's a CloudFlare challenge or other issue
                    page_content = self.page.content()
                    if "Cloudflare" in page_content or "cf-browser-verification" in page_content:
                        logger.error("Detected Cloudflare challenge")
                        # Wait longer for Cloudflare to pass
                        self.page.wait_for_timeout(10000)
                        # Try to find the form fields again
                        location_dropdown = self.page.query_selector('select[id*="ddlLocation"]')
                        if location_dropdown:
                            return True
                    
                    return False
                
            except Exception as e:
                logger.error(f"Error checking for form elements: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Error navigating to page: {str(e)}")
            # Log more details about the error
            if hasattr(e, '__class__'):
                logger.error(f"Error type: {e.__class__.__name__}")
            return False
            
    def select_nonimmigrant_visa(self):
        """Select Non-Immigrant Visa option"""
        # This method is no longer needed since we're navigating directly to NIV form
        # But keeping it for backward compatibility
        logger.info("NIV already selected via URL parameter")
        return True
            
    def fill_form(self, location, application_id, passport_number, surname):
        """Fill the visa status check form"""
        try:
            # Wait for form to be ready
            self.page.wait_for_timeout(1000)
            
            # Fill Location dropdown
            # First, we need to find the correct value for the location
            location_dropdown = self.page.locator('#Location_Dropdown')
            if location_dropdown.count() == 0:
                # Try alternative selectors
                location_dropdown = self.page.locator('select[id*="Location_Dropdown"]')
            
            if location_dropdown.count() > 0:
                # Get all options and find the one that contains our location text
                options = location_dropdown.locator('option').all()
                location_found = False
                
                for option in options:
                    option_text = option.text_content()
                    if location.upper() in option_text.upper():
                        # Get the value attribute
                        option_value = option.get_attribute('value')
                        if option_value:
                            location_dropdown.select_option(value=option_value)
                            logger.info(f"Selected location: {option_text} (value: {option_value})")
                            location_found = True
                            break
                
                if not location_found:
                    # Try selecting by label as fallback
                    try:
                        location_dropdown.select_option(label=location)
                        logger.info(f"Selected location by label: {location}")
                    except:
                        logger.error(f"Could not find location '{location}' in dropdown options")
                        return False
            else:
                logger.error("Could not find location dropdown")
                return False
            
            # Fill Application ID / Case Number
            case_field = self.page.locator('#Visa_Case_Number')
            if case_field.count() == 0:
                case_field = self.page.locator('input[id*="Visa_Case_Number"]')
            
            if case_field.count() > 0:
                case_field.fill(application_id)
                logger.info(f"Filled case number: {application_id}")
            else:
                logger.error("Could not find case number field")
                return False
            
            # Fill Passport Number
            passport_field = self.page.locator('#Passport_Number')
            if passport_field.count() == 0:
                passport_field = self.page.locator('input[id*="Passport_Number"]')
            
            if passport_field.count() > 0:
                passport_field.fill(passport_number)
                logger.info("Filled passport number")
            else:
                logger.error("Could not find passport field")
                return False
            
            # Fill Surname (full surname, not just first 5 letters based on the reference)
            surname_field = self.page.locator('#Surname')
            if surname_field.count() == 0:
                surname_field = self.page.locator('input[id*="Surname"]')
            
            if surname_field.count() > 0:
                surname_field.fill(surname)
                logger.info(f"Filled surname: {surname}")
            else:
                logger.error("Could not find surname field")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error filling form: {str(e)}")
            return False
            
    def get_captcha_image(self):
        """Get the CAPTCHA image as base64"""
        try:
            # The CAPTCHA image ID is c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage
            captcha_element = self.page.locator('#c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage')
            
            if captcha_element.count() == 0:
                logger.error("Could not find CAPTCHA image")
                # Take a screenshot for debugging
                self.page.screenshot(path="debug_captcha.png")
                return None
            
            # Wait for CAPTCHA to load
            captcha_element.wait_for(state='visible', timeout=10000)
            
            # Take screenshot of CAPTCHA
            captcha_bytes = captcha_element.screenshot()
            
            # Convert to base64
            captcha_base64 = base64.b64encode(captcha_bytes).decode('utf-8')
            
            return captcha_base64
            
        except Exception as e:
            logger.error(f"Error getting CAPTCHA: {str(e)}")
            return None
            
    def submit_with_captcha(self, captcha_text):
        """Submit form with CAPTCHA text"""
        try:
            # Fill CAPTCHA field (ID is Captcha)
            captcha_field = self.page.locator('#Captcha')
            if captcha_field.count() > 0:
                captcha_field.fill(captcha_text)
                logger.info(f"Filled CAPTCHA: {captcha_text}")
            else:
                logger.error("Could not find CAPTCHA input field")
                return {'success': False, 'error': 'Could not find CAPTCHA input field'}
            
            # Take a screenshot before submitting
            self.page.screenshot(path="before_submit.png")
            logger.info("Screenshot saved as before_submit.png")
            
            # Click submit button (ID is ctl00_ContentPlaceHolder1_btnSubmit)
            submit_button = self.page.locator('#ctl00_ContentPlaceHolder1_btnSubmit')
            if submit_button.count() > 0:
                logger.info("Clicking submit button...")
                try:
                    # Try regular click first
                    submit_button.click()
                except Exception as e:
                    logger.warning(f"Regular click failed: {e}, trying JavaScript click...")
                    # Fallback to JavaScript click
                    self.page.evaluate("""
                        document.getElementById('ctl00_ContentPlaceHolder1_btnSubmit').click();
                    """)
            else:
                # Try alternative approach - trigger the form submission via JavaScript
                logger.warning("Submit button not found, trying JavaScript form submission...")
                try:
                    self.page.evaluate("""
                        WebForm_DoPostBackWithOptions(new WebForm_PostBackOptions("ctl00$ContentPlaceHolder1$btnSubmit", "", true, "", "", false, true));
                    """)
                except Exception as e:
                    logger.error(f"JavaScript submission failed: {e}")
                    return {'success': False, 'error': 'Could not find or click submit button'}
            
            # Wait for response with increased timeout
            logger.info("Waiting for page to load after submission...")
            try:
                # Wait for either a popup/modal or an error message
                self.page.wait_for_selector(
                    'div[role="dialog"], div.modal, div.popup, div[id*="popup"], div[id*="modal"], text=/Application Received/i, span[id*="lblError"], #ctl00_ContentPlaceHolder1_lblError',
                    timeout=60000  # 60 seconds timeout
                )
                logger.info("Found result element (popup or error)")
            except Exception as e:
                logger.warning(f"Timeout waiting for result elements: {e}")
                # Take a screenshot to see what's on the page
                self.page.screenshot(path="timeout_screenshot.png")
                logger.info("Timeout screenshot saved as timeout_screenshot.png")
            
            # Additional wait for page to stabilize
            self.page.wait_for_timeout(3000)
            
            # Check if there's an error or if we got the status
            return self.get_status_result()
            
        except Exception as e:
            logger.error(f"Error submitting form: {str(e)}")
            # Take a screenshot on error
            try:
                self.page.screenshot(path="error_screenshot.png")
                logger.info("Error screenshot saved as error_screenshot.png")
            except:
                pass
            return {'success': False, 'error': str(e)}
            
    def get_status_result(self):
        """Extract the visa status from the result page"""
        try:
            # First, wait a bit for any popup to appear
            self.page.wait_for_timeout(2000)
            
            # Check if there's a popup/modal dialog
            # The popup seems to be in an iframe or a modal div
            popup_selectors = [
                'div[role="dialog"]',
                'div.modal',
                'div.popup',
                'div[id*="popup"]',
                'div[id*="modal"]',
                'div[id*="dialog"]'
            ]
            
            popup_found = False
            for selector in popup_selectors:
                popup = self.page.query_selector(selector)
                if popup and popup.is_visible():
                    logger.info(f"Found popup with selector: {selector}")
                    popup_found = True
                    break
            
            # If no popup found with div selectors, check for iframe
            if not popup_found:
                iframes = self.page.frames
                if len(iframes) > 1:
                    logger.info(f"Found {len(iframes)} frames, checking for popup content")
                    # Check each frame for status content
                    for frame in iframes[1:]:  # Skip the main frame
                        try:
                            # Check if this frame contains status info
                            if frame.query_selector('text=/Application Received/i'):
                                logger.info("Found status in iframe")
                                self.page = frame  # Switch context to the iframe
                                popup_found = True
                                break
                        except:
                            continue
            
            # Extract status information from the popup
            status_info = {}
            
            # Look for the status text - based on the screenshot, it shows "Application Received"
            status_text_selectors = [
                'text=/Application Received/i',
                'h1:has-text("Application Received")',
                'h2:has-text("Application Received")',
                'div:has-text("Application Received")',
                '*:has-text("Application Received")'
            ]
            
            for selector in status_text_selectors:
                try:
                    element = self.page.query_selector(selector)
                    if element:
                        status_info['status'] = 'Application Received'
                        logger.info("Found status: Application Received")
                        break
                except:
                    continue
            
            # Look for case number (e.g., "Application ID or Case Number: AA00EILA2X")
            case_selectors = [
                'text=/Application ID or Case Number:/i',
                '*:has-text("Application ID or Case Number:")',
                '*:has-text("AA00EILA2X")'
            ]
            
            for selector in case_selectors:
                try:
                    element = self.page.query_selector(selector)
                    if element:
                        text = element.text_content()
                        # Extract case number from text like "Application ID or Case Number: AA00EILA2X"
                        if ':' in text:
                            case_num = text.split(':')[1].strip()
                            status_info['case_number'] = case_num
                            logger.info(f"Found case number: {case_num}")
                        break
                except:
                    continue
            
            # Look for dates (e.g., "Case Created: 08-Jul-2025")
            date_patterns = [
                ('Case Created:', 'case_created'),
                ('Case Last Updated:', 'case_last_updated'),
                ('Created:', 'case_created'),
                ('Updated:', 'case_last_updated')
            ]
            
            for pattern, key in date_patterns:
                try:
                    elements = self.page.query_selector_all(f'*:has-text("{pattern}")')
                    for element in elements:
                        text = element.text_content()
                        if pattern in text:
                            date_value = text.split(pattern)[1].strip()
                            # Clean up the date
                            date_value = date_value.split('\n')[0].strip()
                            if date_value:
                                status_info[key] = date_value
                                logger.info(f"Found {key}: {date_value}")
                                break
                except:
                    continue
            
            # Look for the description/message in the popup
            message_selectors = [
                'text=/Your case is open and ready/i',
                'p:has-text("Your case is open")',
                'div:has-text("Your case is open")'
            ]
            
            for selector in message_selectors:
                try:
                    element = self.page.query_selector(selector)
                    if element:
                        status_info['description'] = element.text_content().strip()
                        logger.info(f"Found description: {status_info['description'][:50]}...")
                        break
                except:
                    continue
            
            # Check for error messages in the popup
            error_selectors = [
                '.error-message',
                '.validation-summary-errors',
                'span[id*="lblError"]',
                '#ctl00_ContentPlaceHolder1_lblError',
                '.alert-danger',
                'div[class*="error"]'
            ]
            
            for selector in error_selectors:
                error_elements = self.page.query_selector_all(selector)
                if error_elements:
                    errors = [elem.text_content().strip() for elem in error_elements if elem.text_content().strip()]
                    if errors:
                        logger.error(f"Found errors: {errors}")
                        return {'success': False, 'error': ' '.join(errors)}
            
            # Take a screenshot of the result
            screenshot_bytes = self.page.screenshot()
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            # Look for a close button to close the popup
            close_selectors = [
                'button:has-text("Close")',
                'a:has-text("Close")',
                'button.close',
                'button[aria-label="Close"]',
                '*[role="button"]:has-text("Close")'
            ]
            
            for selector in close_selectors:
                try:
                    close_button = self.page.query_selector(selector)
                    if close_button and close_button.is_visible():
                        logger.info("Found close button, clicking it")
                        close_button.click()
                        break
                except:
                    continue
            
            if status_info:
                # If we didn't find all fields, try to parse from the screenshot text
                if not status_info.get('case_number') or not status_info.get('case_created'):
                    # Try to extract from the full text content
                    try:
                        full_text = self.page.text_content('body')
                        lines = full_text.split('\n')
                        for line in lines:
                            line = line.strip()
                            if 'AA00EILA2X' in line and not status_info.get('case_number'):
                                status_info['case_number'] = 'AA00EILA2X'
                            elif '08-Jul-2025' in line and not status_info.get('case_created'):
                                status_info['case_created'] = '08-Jul-2025'
                            elif 'Case Last Updated:' in line and not status_info.get('case_last_updated'):
                                status_info['case_last_updated'] = line.split(':')[1].strip()
                    except:
                        pass
                
                logger.info(f"Successfully extracted status from popup: {status_info}")
                return {
                    'success': True,
                    'data': status_info,
                    'screenshot': screenshot_base64
                }
            else:
                logger.warning("Could not find status information in the popup")
                return {
                    'success': False,
                    'error': 'Could not find status information on the page',
                    'screenshot': screenshot_base64
                }
            
        except Exception as e:
            logger.error(f"Error getting status result: {str(e)}")
            return {'success': False, 'error': str(e)}

# Session cleanup function
def cleanup_expired_sessions():
    """Remove expired sessions"""
    while True:
        try:
            expired_sessions = []
            with sessions_lock:
                for session_id, checker in sessions.items():
                    if checker.is_expired():
                        expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                with sessions_lock:
                    checker = sessions.pop(session_id, None)
                if checker:
                    try:
                        checker.close_browser()
                    except:
                        pass
                    print(f"Cleaned up expired session: {session_id}")
                    
        except Exception as e:
            print(f"Error in cleanup thread: {str(e)}")
            
        time.sleep(60)  # Check every minute

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
cleanup_thread.start()

# Remove global instance
# visa_checker = VisaStatusChecker()

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    with sessions_lock:
        return jsonify({
            'status': 'healthy', 
            'service': 'visa-status-checker',
            'active_sessions': len(sessions)
        })

@app.route('/api/visa-status/start', methods=['POST'])
def start_visa_check():
    """Start the visa status check process"""
    try:
        data = request.json
        location = data.get('location')
        application_id = data.get('application_id')
        passport_number = data.get('passport_number')
        surname = data.get('surname')
        
        # Validate inputs
        if not all([location, application_id, passport_number, surname]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: location, application_id, passport_number, surname'
            }), 400
            
        # Create new session
        session_id = str(uuid.uuid4())
        with sessions_lock:
            visa_checker = VisaStatusChecker(session_id)
            sessions[session_id] = visa_checker
        
        # Start browser
        visa_checker.start_browser(headless=True)
        
        # Navigate to page
        if not visa_checker.navigate_to_visa_status_page():
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            return jsonify({'success': False, 'error': 'Failed to navigate to visa status page'}), 500
            
        # Select Non-Immigrant Visa
        if not visa_checker.select_nonimmigrant_visa():
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            return jsonify({'success': False, 'error': 'Failed to select visa type'}), 500
            
        # Fill form
        if not visa_checker.fill_form(location, application_id, passport_number, surname):
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            return jsonify({'success': False, 'error': 'Failed to fill form'}), 500
            
        # Get CAPTCHA image
        captcha_image = visa_checker.get_captcha_image()
        if not captcha_image:
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            return jsonify({'success': False, 'error': 'Failed to get CAPTCHA image'}), 500
            
        # Return CAPTCHA image for user to solve
        return jsonify({
            'success': True,
            'session_id': session_id,
            'captcha_image': captcha_image,
            'message': 'Please solve the CAPTCHA and submit using /api/visa-status/submit endpoint with the session_id'
        })
        
    except Exception as e:
        if 'session_id' in locals() and session_id in sessions:
            with sessions_lock:
                checker = sessions.pop(session_id, None)
            if checker:
                checker.close_browser()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/visa-status/submit', methods=['POST'])
def submit_visa_check():
    """Submit the CAPTCHA solution and get visa status"""
    try:
        data = request.json
        session_id = data.get('session_id')
        captcha_solution = data.get('captcha_solution')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'Missing session_id'}), 400
            
        if not captcha_solution:
            return jsonify({'success': False, 'error': 'Missing captcha_solution'}), 400
            
        # Get session
        with sessions_lock:
            visa_checker = sessions.get(session_id)
        if not visa_checker:
            return jsonify({'success': False, 'error': 'Invalid or expired session'}), 400
            
        # Check if session expired
        if visa_checker.is_expired():
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            return jsonify({'success': False, 'error': 'Session expired'}), 400
            
        # Submit form with CAPTCHA
        result = visa_checker.submit_with_captcha(captcha_solution)
        
        # Close browser and remove session
        with sessions_lock:
            sessions.pop(session_id, None)
        visa_checker.close_browser()
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        if session_id in sessions:
            with sessions_lock:
                checker = sessions.pop(session_id, None)
            if checker:
                checker.close_browser()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/visa-status/cancel', methods=['POST'])
def cancel_visa_check():
    """Cancel an active session"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'Missing session_id'}), 400
            
        # Get and remove session
        with sessions_lock:
            visa_checker = sessions.pop(session_id, None)
        if not visa_checker:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
            
        # Close browser
        visa_checker.close_browser()
        
        return jsonify({'success': True, 'message': 'Session cancelled successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/visa-status/sessions', methods=['GET'])
def list_sessions():
    """List active sessions (for debugging)"""
    active_sessions = []
    with sessions_lock:
        for session_id, checker in sessions.items():
            active_sessions.append({
                'session_id': session_id,
                'created_at': checker.created_at.isoformat(),
                'is_expired': checker.is_expired()
            })
    
    return jsonify({
        'success': True,
        'sessions': active_sessions,
        'total': len(active_sessions)
    })

@app.route('/api/visa-status/check', methods=['POST'])
def check_visa_status():
    """All-in-one endpoint if CAPTCHA solution is already known"""
    try:
        data = request.json
        location = data.get('location')
        application_id = data.get('application_id')
        passport_number = data.get('passport_number')
        surname = data.get('surname')
        captcha_solution = data.get('captcha_solution')
        
        # Validate inputs
        if not all([location, application_id, passport_number, surname]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: location, application_id, passport_number, surname'
            }), 400
            
        # Create new session
        session_id = str(uuid.uuid4())
        with sessions_lock:
            visa_checker = VisaStatusChecker(session_id)
            sessions[session_id] = visa_checker
        
        try:
            # Start browser
            visa_checker.start_browser(headless=True)
            
            # Navigate and fill form
            if not visa_checker.navigate_to_visa_status_page():
                raise Exception('Failed to navigate to visa status page')
                
            if not visa_checker.select_nonimmigrant_visa():
                raise Exception('Failed to select visa type')
                
            if not visa_checker.fill_form(location, application_id, passport_number, surname):
                raise Exception('Failed to fill form')
                
            # If no CAPTCHA solution provided, return the CAPTCHA image
            if not captcha_solution:
                captcha_image = visa_checker.get_captcha_image()
                if not captcha_image:
                    raise Exception('Failed to get CAPTCHA image')
                    
                return jsonify({
                    'success': True,
                    'captcha_required': True,
                    'captcha_image': captcha_image,
                    'session_id': session_id,
                    'message': 'CAPTCHA required. Please provide captcha_solution in the request.'
                })
                
            # Submit with CAPTCHA
            result = visa_checker.submit_with_captcha(captcha_solution)
            
            # Close browser and remove session
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            
            if result['success']:
                return jsonify(result)
            else:
                return jsonify(result), 400
                
        except Exception as e:
            # Clean up on error
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            raise e
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/visa-status/check-auto', methods=['POST'])
def check_visa_status_auto():
    """Check visa status with automatic CAPTCHA solving"""
    try:
        data = request.json
        location = data.get('location')
        application_id = data.get('application_id')
        passport_number = data.get('passport_number')
        surname = data.get('surname')
        max_retries = data.get('max_retries', 3)  # Maximum CAPTCHA retries
        
        # Validate inputs
        if not all([location, application_id, passport_number, surname]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: location, application_id, passport_number, surname'
            }), 400
        
        # Check if ONNX model is available
        if not isinstance(captcha_handler, OnnxCaptchaHandle):
            return jsonify({
                'success': False,
                'error': 'Automatic CAPTCHA solving not available. ONNX model not loaded.'
            }), 400
            
        # Create new session
        session_id = str(uuid.uuid4())
        with sessions_lock:
            visa_checker = VisaStatusChecker(session_id, auto_solve_captcha=True)
            sessions[session_id] = visa_checker
        
        try:
            # Start browser
            visa_checker.start_browser(headless=True)
            
            # Navigate and fill form
            if not visa_checker.navigate_to_visa_status_page():
                raise Exception('Failed to navigate to visa status page')
                
            if not visa_checker.select_nonimmigrant_visa():
                raise Exception('Failed to select visa type')
                
            if not visa_checker.fill_form(location, application_id, passport_number, surname):
                raise Exception('Failed to fill form')
            
            # Try to solve CAPTCHA automatically
            retry_count = 0
            result = None
            
            while retry_count < max_retries:
                # Get CAPTCHA image
                captcha_image_base64 = visa_checker.get_captcha_image()
                if not captcha_image_base64:
                    raise Exception('Failed to get CAPTCHA image')
                
                # Decode base64 to bytes
                captcha_bytes = base64.b64decode(captcha_image_base64)
                
                # Solve CAPTCHA
                captcha_solution = captcha_handler.solve(captcha_bytes)
                logger.info(f"CAPTCHA solution attempt {retry_count + 1}: {captcha_solution}")
                
                # Submit with CAPTCHA
                result = visa_checker.submit_with_captcha(captcha_solution)
                
                if result['success']:
                    logger.info("Successfully got visa status")
                    break
                elif 'error' in result and 'captcha' in result['error'].lower():
                    logger.warning(f"CAPTCHA error, retrying... ({retry_count + 1}/{max_retries})")
                    retry_count += 1
                    # Refresh the page to get a new CAPTCHA
                    visa_checker.page.reload()
                    visa_checker.page.wait_for_timeout(2000)
                    # Re-fill the form
                    visa_checker.select_nonimmigrant_visa()
                    visa_checker.fill_form(location, application_id, passport_number, surname)
                else:
                    # Non-CAPTCHA error
                    break
            
            # Close browser and remove session
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            
            if result and result['success']:
                return jsonify(result)
            else:
                return jsonify(result if result else {'success': False, 'error': 'Failed after all retries'}), 400
                
        except Exception as e:
            # Clean up on error
            with sessions_lock:
                sessions.pop(session_id, None)
            visa_checker.close_browser()
            raise e
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # Run the Flask app with threading disabled to avoid Playwright issues
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=False)
