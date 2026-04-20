import warnings
warnings.filterwarnings("ignore")

import serial
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1327
from PIL import ImageFont
import keyboard
import time
import qwiic_buzzer
from gpiozero import Servo
import adafruit_fingerprint
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone
import base64
import threading

# --- 1. Hardware Setup ---

# OLED Screen Setup
screen_serial = i2c(port=1, address=0x3C)
device = ssd1327(screen_serial)

# Fingerprint Sensor Setup
uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
finger = adafruit_fingerprint.Adafruit_Fingerprint(uart)

# Servo Setup
servo = Servo(13, min_pulse_width=0.5/1000, max_pulse_width=2.5/1000)
servo.value = None

# Buzzer Setup
try:
    my_buzzer = qwiic_buzzer.QwiicBuzzer()
    if not my_buzzer.is_connected():
        print("Buzzer not connected.")
        my_buzzer = None
except Exception as e:
    print(f"Buzzer init failed: {e}")
    my_buzzer = None

# --- 2. Firebase Setup ---
db = None
firebase_online = False
try:
    cred = credentials.Certificate("key.json")
    firebase_admin.initialize_app(cred, {
        'projectId': 'sitesync-ff98c'
    })
    db = firestore.client()
    # Quick connectivity check
    db.collection('Jobs').limit(1).stream()
    firebase_online = True
    doc_buzz = db.collection("Devices").document("Buzzer1")
    doc_servo = db.collection("Devices").document("Servo1")
    doc_fing = db.collection("Devices").document("Fingerprint1")
    print("Firebase connected successfully.")
except Exception as e:
    print(f"Firebase init failed: {e}")
    firebase_online = False

# --- 3. Font Setup ---
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    header_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
except IOError:
    font = ImageFont.load_default()
    header_font = ImageFont.load_default()
    small_font = ImageFont.load_default()

# --- 4. Admin PIN ---
ADMIN_PIN = [0, 0, 0, 0]

# --- 5. Idle Screensaver State ---
last_activity = time.time()
IDLE_TIMEOUT = 10  # seconds
screensaver_active = False

def reset_activity():
    global last_activity, screensaver_active
    last_activity = time.time()
    screensaver_active = False

# --- 6. Buzzer Feedback ---
def beep_success():
    """2 short beeps for success."""
    if my_buzzer is None:
        return
    try:
        for _ in range(2):
            my_buzzer.on()
            time.sleep(0.15)
            my_buzzer.off()
            time.sleep(0.15)
    except Exception as e:
        print(f"Buzzer error: {e}")

def beep_error():
    """1 long beep for error."""
    if my_buzzer is None:
        return
    try:
        my_buzzer.on()
        time.sleep(0.6)
        my_buzzer.off()
    except Exception as e:
        print(f"Buzzer error: {e}")

# --- 7. Servo Trigger ---
def trigger_servo():
    """Triggers servo sequence."""
    try:
        print("Servo triggered...")
        servo.max()
        time.sleep(2)
        servo.min()
        time.sleep(2)
        servo.value = None
        print("Servo done.")
    except Exception as e:
        print(f"Servo error: {e}")

# --- 8. Display Helpers ---
def show_message(title, msg):
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 127), outline="white")
        draw.text((30, 40), title, fill="white", font=header_font)
        draw.text((20, 70), msg, fill="white", font=font)

def show_confirmation(action, name, company):
    """Shows a detailed confirmation screen after clock in/out."""
    now = datetime.now().strftime("%I:%M %p")
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 127), outline="white")
        draw.text((25, 8), action, fill="white", font=header_font)
        draw.line((10, 22, 118, 22), fill="white")
        display_name = name if len(name) <= 16 else name[:14] + ".."
        display_company = company if len(company) <= 16 else company[:14] + ".."
        draw.text((10, 30), display_name, fill="white", font=font)
        draw.text((10, 48), display_company, fill="white", font=font)
        draw.line((10, 62, 118, 62), fill="white")
        draw.text((10, 70), "Time:", fill="white", font=font)
        draw.text((10, 84), now, fill="white", font=header_font)

def show_screensaver():
    """Draws the branded screensaver with time, date, and network status."""
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%b %d %Y")
    status = "Online" if firebase_online else "Offline"
    status_color = "white"

    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 127), outline="white")
        # Brand name
        draw.text((28, 10), "SiteSync", fill="white", font=header_font)
        draw.line((10, 25, 118, 25), fill="white")
        # Time
        draw.text((22, 38), time_str, fill="white", font=header_font)
        # Date
        draw.text((20, 58), date_str, fill="white", font=font)
        draw.line((10, 75, 118, 75), fill="white")
        # Network status
        dot = "?"
        draw.text((20, 82), dot, fill=status_color, font=font)
        draw.text((32, 82), status, fill=status_color, font=font)

# --- 9. Loading Animation ---
def show_loading(message, stop_event):
    """Displays an animated loading screen. Runs in a separate thread."""
    dots = 0
    while not stop_event.is_set():
        dot_str = "." * (dots % 4)
        with canvas(device) as draw:
            draw.rectangle((0, 0, 127, 127), outline="white")
            draw.text((30, 45), message, fill="white", font=header_font)
            draw.text((50, 65), dot_str, fill="white", font=header_font)
        dots += 1
        time.sleep(0.4)

def fetch_with_loading(message, fetch_function):
    """Runs a Firebase fetch while showing a loading animation."""
    stop_event = threading.Event()
    loader = threading.Thread(target=show_loading, args=(message, stop_event))
    loader.daemon = True
    loader.start()
    try:
        result = fetch_function()
    finally:
        stop_event.set()
        loader.join()
    return result

# --- 10. Scrollable List UI ---
def scrollable_list(title, items, display_key=None, show_back_hint=True):
    """
    Shows a scrollable list on the OLED and returns the selected item.
    Returns None if user cancels with left/esc.
    """
    if not items:
        show_message("No Data", "List is empty")
        time.sleep(2)
        return None

    current = 0

    def draw_list():
        with canvas(device) as draw:
            draw.rectangle((0, 0, 127, 127), outline="white")
            draw.text((10, 5), title, fill="white", font=header_font)
            draw.line((10, 20, 118, 20), fill="white")

            max_visible = 4
            start = max(0, current - max_visible + 1)
            visible = items[start:start + max_visible]

            for i, item in enumerate(visible):
                actual_index = start + i
                y_pos = 28 + (i * 18)

                if display_key and isinstance(item, dict):
                    label = str(item.get(display_key, "?"))
                else:
                    label = str(item)

                if len(label) > 16:
                    label = label[:14] + ".."

                if actual_index == current:
                    draw.rectangle((5, y_pos - 2, 122, y_pos + 11), fill="white")
                    draw.text((10, y_pos), label, fill="black", font=font)
                else:
                    draw.text((10, y_pos), label, fill="white", font=font)

            # Back hint at bottom
            if show_back_hint:
                draw.line((10, 104, 118, 104), fill="white")
                draw.text((10, 108), "< LEFT to go back", fill="white", font=small_font)

    draw_list()

    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            reset_activity()
            if event.name == 'down':
                current = (current + 1) % len(items)
                draw_list()
            elif event.name == 'up':
                current = (current - 1) % len(items)
                draw_list()
            elif event.name == 'right' or event.name == 'enter':
                return items[current]
            elif event.name == 'left' or event.name == 'esc':
                return None

# --- 11. Admin PIN Entry ---
def enter_pin():
    attempts = 0
    max_attempts = 3

    while attempts < max_attempts:
        entered = [0, 0, 0, 0]
        current_pos = 0

        def draw_pin(active_pos, digits, wrong=False):
            with canvas(device) as draw:
                draw.rectangle((0, 0, 127, 127), outline="white")
                draw.text((20, 8), "Admin PIN", fill="white", font=header_font)
                draw.line((10, 22, 118, 22), fill="white")

                for i in range(4):
                    x = 14 + (i * 26)
                    y = 45
                    if i == active_pos:
                        draw.rectangle((x - 2, y - 2, x + 18, y + 16), outline="white", fill="white")
                        draw.text((x + 3, y), str(digits[i]), fill="black", font=header_font)
                    else:
                        draw.rectangle((x - 2, y - 2, x + 18, y + 16), outline="white")
                        draw.text((x + 3, y), str(digits[i]), fill="white", font=header_font)

                if wrong:
                    remaining = max_attempts - attempts
                    draw.text((10, 80), f"Wrong! {remaining} left", fill="white", font=font)
                else:
                    draw.text((10, 80), "UP/DN: change digit", fill="white", font=small_font)
                    draw.text((10, 95), "SELECT: confirm digit", fill="white", font=small_font)

        draw_pin(current_pos, entered)

        while current_pos < 4:
            event = keyboard.read_event()
            if event.event_type == keyboard.KEY_DOWN:
                reset_activity()
                if event.name == 'up':
                    entered[current_pos] = (entered[current_pos] + 1) % 10
                    draw_pin(current_pos, entered)
                elif event.name == 'down':
                    entered[current_pos] = (entered[current_pos] - 1) % 10
                    draw_pin(current_pos, entered)
                elif event.name == 'right' or event.name == 'enter':
                    current_pos += 1
                    if current_pos < 4:
                        draw_pin(current_pos, entered)
                elif event.name == 'left' or event.name == 'esc':
                    return False

        if entered == ADMIN_PIN:
            show_message("Access", "Granted!")
            beep_success()
            time.sleep(1)
            return True
        else:
            attempts += 1
            draw_pin(0, entered, wrong=True)
            beep_error()
            time.sleep(2)

    show_message("Locked Out!", "Try Later")
    beep_error()
    time.sleep(3)
    return False

# --- 12. Admin Submenu ---
admin_items = ["Test Servo", "Test Buzzer", "Test Finger Print", "Back"]
admin_selection = 0

def draw_admin_menu():
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 127), outline="white")
        draw.text((25, 5), "Admin Menu", fill="white", font=header_font)
        draw.line((10, 20, 118, 20), fill="white")

        for i, item in enumerate(admin_items):
            y_pos = 28 + (i * 18)
            if i == admin_selection:
                draw.rectangle((5, y_pos - 2, 122, y_pos + 11), fill="white")
                draw.text((10, y_pos), item, fill="black", font=font)
            else:
                draw.text((10, y_pos), item, fill="white", font=font)

def admin_menu():
    global admin_selection
    admin_selection = 0
    draw_admin_menu()

    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            reset_activity()
            if event.name == 'down':
                admin_selection = (admin_selection + 1) % len(admin_items)
                draw_admin_menu()
            elif event.name == 'up':
                admin_selection = (admin_selection - 1) % len(admin_items)
                draw_admin_menu()
            elif event.name == 'right' or event.name == 'enter':
                selected = admin_items[admin_selection]
                if selected == "Test Servo":
                    test_servo()
                elif selected == "Test Buzzer":
                    test_buzzer()
                elif selected == "Test Finger Print":
                    show_message("Scanning...", "Place Finger")
                    test_fingerprint()
                    time.sleep(2)
                elif selected == "Back":
                    return
                draw_admin_menu()
            elif event.name == 'left' or event.name == 'esc':
                return

# --- 13. Fingerprint Capture ---
def capture_fingerprint():
    show_message("Scan Finger", "Place Finger Now")
    print("Waiting for fingerprint...")

    start_time = time.time()
    timeout = 15

    while (time.time() - start_time) < timeout:
        i = finger.get_image()

        if i == adafruit_fingerprint.OK:
            print("Fingerprint image captured.")
            try:
                raw_data = finger.get_fpdata(sensorbuffer="image")
                b64_string = base64.b64encode(bytes(raw_data)).decode('utf-8')
                return b64_string
            except Exception as e:
                print(f"Failed to read fingerprint buffer: {e}")
                return "FINGERPRINT_CAPTURED_NO_RAW_DATA"
        elif i == adafruit_fingerprint.IMAGEFAIL:
            show_message("Scan Failed", "Try Again")
            time.sleep(1)
            return None

    show_message("Timeout", "No Finger Seen")
    time.sleep(1)
    return None

# --- 14. Firebase Helpers ---
def fetch_active_jobs():
    if db is None: return []
    try:
        query = db.collection('Jobs').where('Status', '==', 'Active').stream()
        jobs = []
        for doc in query:
            data = doc.to_dict()
            data['_doc_id'] = doc.id
            jobs.append(data)
        return jobs
    except Exception as e:
        print(f"Error fetching jobs: {e}")
        return []

def check_already_clocked_in(employee_name, job_id):
    if db is None: return False
    try:
        results = db.collection('PunchLog') \
            .where('EmployeeName', '==', employee_name) \
            .where('JobId', '==', job_id) \
            .where('ClockOut', '==', '') \
            .stream()
        for _ in results: return True
        return False
    except Exception as e:
        print(f"Error checking clock-in status: {e}")
        return False

def find_open_punch(employee_name, job_id):
    if db is None: return None, None
    try:
        results = db.collection('PunchLog') \
            .where('EmployeeName', '==', employee_name) \
            .where('JobId', '==', job_id) \
            .where('ClockOut', '==', '') \
            .stream()
        for doc in results:
            return doc.id, doc.to_dict()
        return None, None
    except Exception as e:
        print(f"Error finding open punch: {e}")
        return None, None

def write_clock_in(employee_name, employee_email, job_id, fingerprint_data):
    if db is None: return False
    try:
        punch_data = {
            'ClockIn': datetime.utcnow(),
            'ClockOut': "",
            'EmployeeName': employee_name,
            'EmployeeEmail': employee_email,
            'JobId': job_id,
            'FingerprintData': fingerprint_data if fingerprint_data else ""
        }
        db.collection('PunchLog').add(punch_data)
        return True
    except Exception as e:
        print(f"Error writing clock-in: {e}")
        return False

def write_clock_out(doc_id, fingerprint_data):
    if db is None: return False
    try:
        db.collection('PunchLog').document(doc_id).update({
            'ClockOut': datetime.utcnow(),
            'FingerprintData': fingerprint_data if fingerprint_data else ""
        })
        print(f"Clock-out written for doc {doc_id}")
        return True
    except Exception as e:
        print(f"Error writing clock-out: {e}")
        return False

def fetch_todays_punches():
    if db is None: return []
    try:
        now = datetime.utcnow()
        start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0)
        results = db.collection('PunchLog').where('ClockIn', '>=', start_of_day).stream()
        punches = []
        for doc in results:
            punches.append(doc.to_dict())
        return punches
    except Exception as e:
        print(f"Error fetching today's punches: {e}")
        return []

def fetch_employee_email(full_name):
    if db is None: return "No Email"
    try:
        parts = full_name.split(" ", 1)
        fname = parts[0]
        lname = parts[1] if len(parts) > 1 else ""
        users = db.collection('Accounts') \
                  .where('firstname', '==', fname) \
                  .where('lastname', '==', lname).stream()
        for user in users:
            return user.to_dict().get('email', "No Email")
    except Exception as e:
        print(f"Error fetching email: {e}")
    return "No Email"

# --- 15. Clock In Flow ---
def clock_in():
    jobs = fetch_with_loading("Loading", fetch_active_jobs)

    if not jobs:
        show_message("No Jobs", "None Available")
        beep_error()
        time.sleep(2)
        return

    job_labels = []
    for job in jobs:
        company = job.get('Company', 'Unknown')
        desc = job.get('Description', '')
        label = f"{company}-{desc}" if desc else company
        job_labels.append({'label': label, 'job': job})

    selected_job_entry = scrollable_list("Select Job", job_labels, display_key='label')
    if selected_job_entry is None: return

    selected_job = selected_job_entry['job']
    job_id = selected_job.get('JobID')
    company = selected_job.get('Company', 'Unknown')
    employees = selected_job.get('JobEmployees', [])
    servo_enabled = selected_job.get('Key', False)

    if not employees:
        show_message("No Employees", "Job is Empty")
        beep_error()
        time.sleep(2)
        return

    selected_name = scrollable_list("Select Name", employees)
    if selected_name is None: return

    # FIXED: Fetch the email variable before using it
    employee_email = fetch_with_loading("Fetching Email", lambda: fetch_employee_email(selected_name))

    # Duplicate clock-in check
    already_in = fetch_with_loading("Checking", lambda: check_already_clocked_in(selected_name, job_id))
    if already_in:
        show_message("Already In!", "Clock Out First")
        beep_error()
        time.sleep(2)
        return

    fingerprint_data = capture_fingerprint()

    # FIXED: Pass employee_email to the write function
    success = fetch_with_loading("Saving", lambda: write_clock_in(selected_name, employee_email, job_id, fingerprint_data))

    if success:
        beep_success()
        show_confirmation("Clocked In!", selected_name, company)
        if servo_enabled: trigger_servo()
        time.sleep(3)
    else:
        beep_error()
        show_message("Failed", "Try Again")
        time.sleep(2)

# --- 16. Clock Out Flow ---
def clock_out():
    jobs = fetch_with_loading("Loading", fetch_active_jobs)
    if not jobs:
        show_message("No Jobs", "None Available")
        beep_error()
        time.sleep(2)
        return

    job_labels = [{'label': f"{j.get('Company','Unknown')}-{j.get('Description','')}" if j.get('Description','') else j.get('Company','Unknown'), 'job': j} for j in jobs]
    selected_job_entry = scrollable_list("Select Job", job_labels, display_key='label')
    if selected_job_entry is None: return

    selected_job = selected_job_entry['job']
    job_id = selected_job.get('JobID')
    company = selected_job.get('Company', 'Unknown')
    employees = selected_job.get('JobEmployees', [])
    servo_enabled = selected_job.get('Key', False)

    selected_name = scrollable_list("Select Name", employees)
    if selected_name is None: return

    doc_id, punch_data = fetch_with_loading("Checking", lambda: find_open_punch(selected_name, job_id))
    if doc_id is None:
        show_message("Not Clocked In", "No Open Punch")
        beep_error()
        time.sleep(2)
        return

    fingerprint_data = capture_fingerprint()
    success = fetch_with_loading("Saving", lambda: write_clock_out(doc_id, fingerprint_data))

    if success:
        beep_success()
        show_confirmation("Clocked Out!", selected_name, company)
        if servo_enabled: trigger_servo()
        time.sleep(3)
    else:
        beep_error()
        show_message("Failed", "Try Again")
        time.sleep(2)

# --- 17. Today's Log ---
def todays_log():
    punches = fetch_with_loading("Loading", fetch_todays_punches)
    if not punches:
        show_message("Today's Log", "No Punches Yet")
        time.sleep(2)
        return

    current = 0
    total = len(punches)

    def draw_punch(index):
        p = punches[index]
        name = p.get('EmployeeName', 'Unknown')
        ci_raw = p.get('ClockIn')
        ci_str = ci_raw.strftime("%I:%M %p") if hasattr(ci_raw, 'strftime') else "N/A"
        co_raw = p.get('ClockOut')
        co_str = co_raw.strftime("%I:%M %p") if hasattr(co_raw, 'strftime') and co_raw != "" else "Active"
        
        with canvas(device) as draw:
            draw.rectangle((0, 0, 127, 127), outline="white")
            draw.text((20, 5), "Today's Log", fill="white", font=header_font)
            draw.text((90, 5), f"{index+1}/{total}", fill="white", font=small_font)
            draw.text((10, 28), name[:16], fill="white", font=font)
            draw.text((10, 65), f"In:  {ci_str}", fill="white", font=font)
            draw.text((10, 80), f"Out: {co_str}", fill="white", font=font)

    draw_punch(current)
    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            reset_activity()
            if event.name == 'down': current = (current + 1) % total; draw_punch(current)
            elif event.name == 'up': current = (current - 1) % total; draw_punch(current)
            elif event.name in ['left', 'esc']: return

# --- 18. Hardware Test Functions ---
def test_servo():
    show_message("Testing...", "Spinning Motor")
    def on_snapshot(doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            data = doc.to_dict()
            state1 = data.get("servo", False)

            if state1:
                print("Firebase says: SERVO ON")
                servo.max()

            else:
                print("Firebase says: SERVO OFF")
                servo.value = None

    listener1 = doc_servo.on_snapshot(on_snapshot)
    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            if event.name in ["left", "esc"]:
                # Turn servo off when exiting
                if servo:
                    servo.value = None
                listener1.unsubscribe()
                return

def test_buzzer():
    show_message("Testing...", "Listening to Firebase")
    def on_snapshot(doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            data = doc.to_dict()
            state2 = data.get("buzzer", False)

            if state2:
                print("Firebase says: BUZZER ON")
                my_buzzer.on()

            else:
                print("Firebase says: BUZZER OFF")
                my_buzzer.off()

    listener2 = doc_buzz.on_snapshot(on_snapshot)
    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            if event.name in ["left", "esc"]:
                # Turn buzzer off when exiting
                if my_buzzer:
                    my_buzzer.off()
                listener2.unsubscribe()
                return
def test_fingerprint():
    show_message("Testing...", "Place Finger")
    start = time.time()
    while (time.time() - start) < 10:
        if finger.get_image() == adafruit_fingerprint.OK:
            show_message("Success!", "Detected")
            time.sleep(2); return
    show_message("Timeout", "No Finger")

# --- 19. Menu State ---
menu_items = ["Clock In", "Clock Out", "Today's Log", "Admin", "Exit"]
current_selection = 0

def draw_menu():
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 127), outline="white")
        draw.text((35, 5), "SiteSync", fill="white", font=header_font)
        draw.line((10, 20, 118, 20), fill="white")
        for i, item in enumerate(menu_items):
            y = 28 + (i * 18)
            if i == current_selection:
                draw.rectangle((5, y-2, 122, y+11), fill="white")
                draw.text((10, y), item, fill="black", font=font)
            else:
                draw.text((10, y), item, fill="white", font=font)

# --- 20. Main Loop ---
print("SiteSync Terminal Active. Use Arrow Keys. (Run with sudo)")
draw_menu()

while True:
    if not screensaver_active and (time.time() - last_activity) > IDLE_TIMEOUT:
        screensaver_active = True

    if screensaver_active:
        show_screensaver()
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            reset_activity(); draw_menu()
        continue

    event = keyboard.read_event()
    if event.event_type == keyboard.KEY_DOWN:
        reset_activity()
        if event.name == 'down': current_selection = (current_selection + 1) % len(menu_items); draw_menu()
        elif event.name == 'up': current_selection = (current_selection - 1) % len(menu_items); draw_menu()
        elif event.name in ['right', 'enter']:
            sel = menu_items[current_selection]
            if sel == "Clock In": clock_in()
            elif sel == "Clock Out": clock_out()
            elif sel == "Today's Log": todays_log()
            elif sel == "Admin": (admin_menu() if enter_pin() else None)
            elif sel == "Exit": device.clear(); break
            draw_menu()