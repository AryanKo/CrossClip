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
import tkinter as tk
from tkinter import scrolledtext

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
ws_app = None

class CrossBoardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CrossBoard Desktop Client")
        self.root.geometry("400x450")
        self.root.configure(bg="#0f172a")
        self.root.attributes("-topmost", True)
        
        # Header
        self.header = tk.Label(root, text="CrossBoard Sync", font=("Helvetica", 16, "bold"), bg="#0f172a", fg="#f8fafc")
        self.header.pack(pady=(15, 5))
        
        # Connection Status
        self.conn_status = tk.Label(root, text="🔴 Offline", font=("Helvetica", 10), bg="#0f172a", fg="#ef4444")
        self.conn_status.pack(pady=5)
        
        # Arm Status
        self.arm_status_frame = tk.Frame(root, bg="#1e293b", padx=10, pady=10)
        self.arm_status_frame.pack(fill="x", padx=20, pady=10)
        
        self.arm_status_lbl = tk.Label(self.arm_status_frame, text="🛡️ System Disarmed", font=("Helvetica", 12, "bold"), bg="#1e293b", fg="#94a3b8")
        self.arm_status_lbl.pack()
        
        # Buttons
        self.btn_frame = tk.Frame(root, bg="#0f172a")
        self.btn_frame.pack(pady=10)
        
        self.btn_arm = tk.Button(self.btn_frame, text="🚨 ARM SYSTEM", bg="#ef4444", fg="white", font=("Helvetica", 10, "bold"), width=15, command=self.arm_system)
        self.btn_arm.grid(row=0, column=0, padx=5)
        
        self.btn_disarm = tk.Button(self.btn_frame, text="🛑 DISARM", bg="#64748b", fg="white", font=("Helvetica", 10, "bold"), width=15, command=self.disarm_system)
        self.btn_disarm.grid(row=0, column=1, padx=5)
        
        # Logs
        tk.Label(root, text="Activity Log", bg="#0f172a", fg="#94a3b8").pack(anchor="w", padx=20)
        self.log_area = scrolledtext.ScrolledText(root, height=10, bg="#1e293b", fg="#f8fafc", font=("Consolas", 9), borderwidth=0)
        self.log_area.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        self.log("Starting CrossBoard Client...")
        
        # Start Threads
        threading.Thread(target=self.monitor_loop, daemon=True).start()
        threading.Thread(target=self.start_listener, daemon=True).start()
        
        # Start Polling initial state
        self.root.after(1000, self.fetch_status)

    def log(self, msg):
        self.log_area.insert(tk.END, msg + "\n")
        self.log_area.see(tk.END)

    def update_ui_status(self, armed):
        if armed:
            self.arm_status_lbl.config(text="🚨 SYSTEM ARMED (Listening)", fg="#ef4444")
        else:
            self.arm_status_lbl.config(text="🛡️ System Disarmed", fg="#94a3b8")

    def arm_system(self):
        try:
            res = requests.post(f"{SERVER_URL}/arm", headers={"x-api-key": API_SECRET})
            if res.status_code == 200:
                self.log("✅ Shield activated. Ready to receive.")
            else:
                self.log(f"⚠️ Auth failed: {res.status_code}")
        except Exception as e:
            self.log("❌ Failed to contact server.")

    def disarm_system(self):
        try:
            res = requests.post(f"{SERVER_URL}/disarm", headers={"x-api-key": API_SECRET})
            if res.status_code == 200:
                self.log("✅ Shield deactivated. System secure.")
        except Exception as e:
            self.log("❌ Failed to contact server.")

    def fetch_status(self):
        try:
            res = requests.get(f"{SERVER_URL}/status", headers={"x-api-key": API_SECRET})
            if res.status_code == 200:
                data = res.json()
                self.update_ui_status(data["armed"])
        except Exception:
            pass
        self.root.after(3000, self.fetch_status) # Poll occasionally

    # --- CLI LOGIC INTEGRATION ---
    def get_clipboard_content(self):
        try:
            win32clipboard.OpenClipboard()
            has_image = win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB)
            has_text = win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT)
            
            if has_image:
                data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
                win32clipboard.CloseClipboard()
                
                # Construct BMP header
                import struct
                bmp_header = struct.pack('<2sLHHL', b'BM', 14 + len(data), 0, 0, 14)
                bmp_data = bmp_header + data
                
                with io.BytesIO(bmp_data) as bmp_io:
                    im = Image.open(bmp_io)
                    with io.BytesIO() as out:
                        im.save(out, format="PNG")
                        return {"type": "image", "content": out.getvalue()}
            
            if has_text:
                text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                if text and text.strip():
                    return {"type": "text", "content": text}
                    
            win32clipboard.CloseClipboard()
        except Exception as e:
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
        return None

    def set_clipboard_content(self, data):
        global last_content, pause_monitoring
        self.log(f"🔄 Syncing {data['type']} from server...")
        with content_lock:
            pause_monitoring = True
        
        try:
            if data['type'] == 'text':
                pyperclip.copy(data['content'])
                with content_lock:
                    last_content = {"type": "text", "content": data['content']}
            elif data['type'] == 'image':
                img_url = f"{SERVER_URL}/uploads/{data['content']}"
                res = requests.get(img_url, headers={"x-api-key": API_SECRET})
                if res.status_code == 200:
                    image = Image.open(io.BytesIO(res.content))
                    output = io.BytesIO()
                    image.convert("RGB").save(output, "BMP")
                    bmp_data = output.getvalue()[14:]
                    output.close()

                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
                    win32clipboard.CloseClipboard()
                    
                    with io.BytesIO() as png_out:
                         image.save(png_out, format="PNG")
                         with content_lock:
                             last_content = {"type": "image", "content": png_out.getvalue()}
            self.log("✅ Sync applied locally")
        except Exception as e:
            self.log(f"❌ Failed to apply sync: {e}")
        finally:
            time.sleep(0.5)
            with content_lock:
                pause_monitoring = False

    def monitor_loop(self):
        global last_content
        with content_lock:
            last_content = self.get_clipboard_content()
        
        while True:
            try:
                time.sleep(1)
                with content_lock:
                    if pause_monitoring:
                         continue
                
                opts = self.get_clipboard_content()
                changed = False
                with content_lock:
                    if opts is not None and last_content is None:
                        changed = True
                    elif opts and last_content:
                        if opts['type'] != last_content['type']:
                            changed = True
                        elif opts['content'] != last_content['content']:
                            changed = True
                
                if changed:
                    with content_lock:
                        last_content = opts
                    
                    # Upload
                    try:
                        if opts['type'] == 'text':
                            res = requests.post(f"{SERVER_URL}/upload", 
                                data={"content": opts['content'], "type": "text"},
                                headers={"x-api-key": API_SECRET}
                            )
                            res.raise_for_status()
                        elif opts['type'] == 'image':
                            files = {'file': ('clipboard.png', opts['content'], 'image/png')}
                            res = requests.post(f"{SERVER_URL}/upload", 
                                data={"type": "image"}, files=files,
                                headers={"x-api-key": API_SECRET}
                            )
                            res.raise_for_status()
                        self.log("📤 Local Change Uploaded")
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code == 403:
                            self.log("🔒 Disarmed. Snippet ignored.")
                        else:
                            self.log(f"⚠️ Upload HTTP Error: {e.response.status_code}")
            except Exception as e:
                pass

    def on_message(self, ws, message):
        try:
            msg = json.loads(message)
            if msg.get("event") == "new_clip":
                self.set_clipboard_content(msg['data'])
            elif msg.get("event") == "system_armed":
                self.update_ui_status(True)
            elif msg.get("event") == "system_disarmed":
                self.update_ui_status(False)
        except Exception as e:
            pass

    def on_error(self, ws, error):
        self.log("❌ WS Error.")

    def on_close(self, ws, close_status_code, close_msg):
        self.conn_status.config(text="🔴 Offline", fg="#ef4444")
        self.log("🔌 Disconnected")
        time.sleep(2)
        self.start_listener()

    def on_open(self, ws):
        self.conn_status.config(text="🟢 Connected to Server", fg="#10b981")
        self.log("🌐 Connected via WebSocket")

    def start_listener(self):
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(f"{WS_URL}?token={API_SECRET}",
                                  on_open=self.on_open,
                                  on_message=self.on_message,
                                  on_error=self.on_error,
                                  on_close=self.on_close)
        ws.run_forever()


if __name__ == "__main__":
    root = tk.Tk()
    app = CrossBoardApp(root)
    root.mainloop()
