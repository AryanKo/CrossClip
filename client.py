import time
import requests
import os
import websocket
import json
import threading
import io
import pyperclip
from PIL import Image, ImageGrab
import win32clipboard
from dotenv import load_dotenv

# --- CONFIG ---
load_dotenv()
SERVER_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"
API_SECRET = os.getenv("API_SECRET")

if not API_SECRET:
    print("❌ ERROR: API_SECRET not set in .env")
    exit(1)

# Global State
last_content = None
content_lock = threading.Lock()
pause_monitoring = False

def get_clipboard_content():
    try:
        # Check image first
        im = ImageGrab.grabclipboard()
        if isinstance(im, Image.Image):
            with io.BytesIO() as output:
                im.save(output, format="PNG")
                return {"type": "image", "content": output.getvalue()} # Bytes
        
        # Check text
        text = pyperclip.paste()
        if text and text.strip():
            return {"type": "text", "content": text} # String
    except Exception:
        pass
    return None

def set_clipboard_content(data):
    global last_content, pause_monitoring
    print(f"🔄 Syncing {data['type']} from server...")
    
    with content_lock:
        pause_monitoring = True
    
    try:
        if data['type'] == 'text':
            pyperclip.copy(data['content'])
            # Update last_content so monitor doesn't see it as "new"
            with content_lock:
                last_content = {"type": "text", "content": data['content']}
                
        elif data['type'] == 'image':
            # Download
            img_url = f"{SERVER_URL}/uploads/{data['content']}"
            res = requests.get(img_url, headers={"x-api-key": API_SECRET})
            if res.status_code == 200:
                image_data = res.content
                
                # Set to Clipboard (Windows)
                image = Image.open(io.BytesIO(image_data))
                output = io.BytesIO()
                image.convert("RGB").save(output, "BMP")
                bmp_data = output.getvalue()[14:] # DIB header offset
                output.close()

                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
                win32clipboard.CloseClipboard()
                
                # Update last_content
                # converting back to PNG bytes to match get_clipboard_content format is expensive
                # so we might just set it to what we think get_clipboard_content will return
                # OR just ignore the next check.
                # Let's try to simulate:
                with io.BytesIO() as png_out:
                    image.save(png_out, format="PNG")
                    with content_lock:
                        last_content = {"type": "image", "content": png_out.getvalue()}
                        
        print("✅ Sync applied locally")
    except Exception as e:
        print(f"❌ Failed to apply sync: {e}")
    finally:
        time.sleep(0.5) # Give OS time to process clipboard
        with content_lock:
            pause_monitoring = False

def monitor_loop():
    global last_content
    print("👀 Clipboard Monitor Started")
    
    # Initialize
    with content_lock:
        last_content = get_clipboard_content()
    
    while True:
        try:
            time.sleep(1)
            
            with content_lock:
                if pause_monitoring:
                    continue
            
            opts = get_clipboard_content() # Read current
            
            # Compare
            changed = False
            with content_lock:
                if opts is None and last_content is not None:
                     # Cleared? We ignore clears usually
                     pass
                elif opts is not None and last_content is None:
                    changed = True
                elif opts and last_content:
                    if opts['type'] != last_content['type']:
                        changed = True
                    elif opts['content'] != last_content['content']:
                        changed = True
            
            if changed:
                print("📤 Local Change Detected! Uploading...")
                with content_lock:
                    last_content = opts
                
                # Upload
                if opts['type'] == 'text':
                    res = requests.post(f"{SERVER_URL}/upload", 
                        data={"content": opts['content'], "type": "text"},
                        headers={"x-api-key": API_SECRET}
                    )
                    res.raise_for_status()
                elif opts['type'] == 'image':
                    files = {'file': ('clipboard.png', opts['content'], 'image/png')}
                    res = requests.post(f"{SERVER_URL}/upload", 
                        data={"type": "image"},
                        files=files,
                        headers={"x-api-key": API_SECRET}
                    )
                    res.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                print("🔒 System Disarmed. Upload ignored.")
            else:
                print(f"⚠️ HTTP Error: {e}")
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Monitor Error: {e}")
            time.sleep(1)

# WebSocket
def on_message(ws, message):
    try:
        msg = json.loads(message)
        if msg.get("event") == "new_clip":
            # We received a new clip. 
            # Check if it matches what we already have (to avoid echo if we just sent it)
            # Implemented via 'pause_monitoring' but also double check content?
            # Creating a hash would be better but keeping it simple.
            set_clipboard_content(msg['data'])
    except Exception as e:
        print(f"WS Error: {e}")

def on_error(ws, error):
    print(f"❌ WebSocket logic error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("🔌 Disconnected")
    time.sleep(2)
    start_listener() # Auto-reconnect

def start_listener():
    websocket.enableTrace(False)
    ws = websocket.WebSocketApp(f"{WS_URL}?token={API_SECRET}",
                              on_message=on_message,
                              on_error=on_error,
                              on_close=on_close)
    ws.run_forever()

if __name__ == "__main__":
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    start_listener()
