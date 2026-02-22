import os
import shutil
import uuid
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Header, Depends, WebSocket, WebSocketDisconnect, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# --- 1. LOAD ENVIRONMENT VARIABLES ---
load_dotenv()
API_SECRET = os.getenv("API_SECRET")

if not API_SECRET:
    print("⚠️ WARNING: API_SECRET not found in .env file! Security is disabled.")

# --- APP CONFIG ---
app = FastAPI(title="CrossClip Secure API")

# Ensure uploads directory exists
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATA MODELS ---
class ClipItem(BaseModel):
    id: str
    type: str  # "text" or "image"
    content: str  # Text content or Filename
    timestamp: str

class SystemStatus(BaseModel):
    armed: bool
    item_count: int
    connected_clients: int

# --- GLOBAL STATE ---
clipboard_history: List[ClipItem] = []
system_state = {"armed": False}

# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Handle disconnected clients gracefully
                pass

manager = ConnectionManager()

# --- SECURITY ---
async def verify_token(x_api_key: Optional[str] = Header(None)):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

async def verify_token_ws(websocket: WebSocket, x_api_key: Optional[str] = None):
    # For WebSocket, we might pass key in query param or header (headers are tricky in JS WebSocket)
    # Simplified: We will trust the connection upgrade or check a query param
    # Implementation detail: Clients should connect like ws://host/ws?token=SECRET
    return True

# --- ENDPOINTS ---

from fastapi.responses import FileResponse

@app.get("/")
def read_root():
    # Serve the main HTML file instead of JSON
    return FileResponse("index.html")

@app.get("/status", response_model=SystemStatus, dependencies=[Depends(verify_token)])
def get_status():
    return {
        "armed": system_state["armed"],
        "item_count": len(clipboard_history),
        "connected_clients": len(manager.active_connections)
    }

@app.post("/arm", dependencies=[Depends(verify_token)])
async def arm_system():
    system_state["armed"] = True
    await manager.broadcast({"event": "system_armed"})
    return {"message": "System ARMED."}

@app.post("/disarm", dependencies=[Depends(verify_token)])
async def disarm_system():
    system_state["armed"] = False
    await manager.broadcast({"event": "system_disarmed"})
    return {"message": "System DISARMED."}

@app.post("/upload", dependencies=[Depends(verify_token)])
async def upload_clip(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
    type: str = Form("text") # Client should specify type explicitly
):
    """
    Handle both text and file uploads.
    STRICT SECURITY: Only allow upload if system is ARMED.
    """
    if not system_state["armed"]:
        raise HTTPException(status_code=403, detail="System is DISARMED. Please ARM to sync.")

    clip_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    
    new_item = None

    if type == "image" and file:
        # Save file
        file_ext = file.filename.split(".")[-1] if file.filename else "png"
        filename = f"{clip_id}.{file_ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        new_item = ClipItem(
            id=clip_id,
            type="image",
            content=filename, # Store filename
            timestamp=timestamp
        )
    elif content:
        # Text content
        new_item = ClipItem(
            id=clip_id,
            type="text",
            content=content,
            timestamp=timestamp
        )
    else:
        raise HTTPException(status_code=400, detail="No content provided")

    # Update History
    clipboard_history.append(new_item)
    if len(clipboard_history) > 50:
        popped_item = clipboard_history.pop(0)
        # Prevent disk storage leak by deleting old image files
        if popped_item.type == "image":
            old_filepath = os.path.join(UPLOAD_DIR, popped_item.content)
            if os.path.exists(old_filepath):
                try:
                    os.remove(old_filepath)
                except Exception:
                    pass

    # Auto-Disarm (One-Shot logic)
    system_state["armed"] = False
    await manager.broadcast({"event": "system_disarmed"})

    # Notify Clients
    await manager.broadcast({
        "event": "new_clip",
        "data": new_item.dict()
    })

    return {"message": "Upload successful", "item": new_item}

@app.get("/latest", response_model=ClipItem, dependencies=[Depends(verify_token)])
def get_latest():
    if not clipboard_history:
        raise HTTPException(status_code=404, detail="Empty history")
    return clipboard_history[-1]

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    # Simple Auth Check
    if token != API_SECRET:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive
            # We can also listen for client messages if needed
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)