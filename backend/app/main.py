from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import secrets
from typing import Dict, Optional
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="POCUS-Health Signaling Server")

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Session:
    def __init__(self, session_id: str, token: str):
        self.session_id = session_id
        self.token = token
        self.created_at = datetime.now()
        self.desktop_ws: Optional[WebSocket] = None
        self.phone_ws: Optional[WebSocket] = None
        self.last_activity = datetime.now()


# In-memory session storage
sessions: Dict[str, Session] = {}

# Session TTL (10 minutes)
SESSION_TTL = timedelta(minutes=10)


class CreateSessionResponse(BaseModel):
    sessionId: str
    token: str
    phoneUrl: str


@app.get("/")
async def root():
    return {"service": "POCUS-Health Signaling Server", "status": "running"}


@app.post("/api/session", response_model=CreateSessionResponse)
async def create_session():
    """Create a new pairing session."""
    session_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    
    session = Session(session_id, token)
    sessions[session_id] = session
    
    # TODO: Make this dynamic based on deployment
    phone_url = f"/m/{session_id}?token={token}"
    
    return CreateSessionResponse(
        sessionId=session_id,
        token=token,
        phoneUrl=phone_url
    )


@app.get("/api/session/{session_id}")
async def get_session_status(session_id: str):
    """Get session status."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "sessionId": session_id,
        "desktopConnected": session.desktop_ws is not None,
        "phoneConnected": session.phone_ws is not None,
        "createdAt": session.created_at.isoformat(),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket signaling endpoint."""
    await websocket.accept()
    
    session: Optional[Session] = None
    role: Optional[str] = None
    
    try:
        # Wait for hello message
        hello_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        
        if hello_msg.get("type") != "hello":
            await websocket.send_json({"type": "error", "message": "Expected hello message"})
            await websocket.close()
            return
        
        role = hello_msg.get("role")
        session_id = hello_msg.get("sessionId")
        token = hello_msg.get("token")
        
        if role not in ["desktop", "phone"]:
            await websocket.send_json({"type": "error", "message": "Invalid role"})
            await websocket.close()
            return
        
        # Validate session and token
        session = sessions.get(session_id)
        if not session or session.token != token:
            await websocket.send_json({"type": "error", "message": "Invalid session or token"})
            await websocket.close()
            return
        
        # Register websocket
        if role == "desktop":
            if session.desktop_ws:
                await websocket.send_json({"type": "error", "message": "Desktop already connected"})
                await websocket.close()
                return
            session.desktop_ws = websocket
        else:  # phone
            if session.phone_ws:
                await websocket.send_json({"type": "error", "message": "Phone already connected"})
                await websocket.close()
                return
            session.phone_ws = websocket
        
        session.last_activity = datetime.now()
        
        # Send ready message
        await websocket.send_json({"type": "ready", "role": role})
        
        # Notify peer if connected
        peer_ws = session.phone_ws if role == "desktop" else session.desktop_ws
        if peer_ws:
            await peer_ws.send_json({"type": "peer-connected", "peer": role})
        
        # Message relay loop
        while True:
            message = await websocket.receive_json()
            session.last_activity = datetime.now()
            
            # Relay to peer
            peer_ws = session.phone_ws if role == "desktop" else session.desktop_ws
            if peer_ws:
                await peer_ws.send_json(message)
            else:
                await websocket.send_json({"type": "error", "message": "Peer not connected"})
    
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "message": "Hello timeout"})
        await websocket.close()
    
    except WebSocketDisconnect:
        pass
    
    finally:
        # Clean up
        if session and role:
            if role == "desktop":
                session.desktop_ws = None
            else:
                session.phone_ws = None
            
            # Notify peer of disconnect
            peer_ws = session.phone_ws if role == "desktop" else session.desktop_ws
            if peer_ws:
                try:
                    await peer_ws.send_json({"type": "peer-disconnected", "peer": role})
                except:
                    pass


async def cleanup_sessions():
    """Periodically clean up expired sessions."""
    while True:
        await asyncio.sleep(60)  # Run every minute
        now = datetime.now()
        expired = [
            sid for sid, session in sessions.items()
            if now - session.last_activity > SESSION_TTL
        ]
        for sid in expired:
            del sessions[sid]


@app.on_event("startup")
async def startup_event():
    """Start background tasks."""
    asyncio.create_task(cleanup_sessions())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
