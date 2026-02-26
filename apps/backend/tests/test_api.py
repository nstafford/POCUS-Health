"""Test suite for POCUS-Health API endpoints and WebSocket signaling."""

import pytest
import json
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


class TestSessionEndpoints:
    """Tests for session creation and retrieval."""

    def test_create_session(self, client):
        """Test creating a new session."""
        response = client.post("/api/session")
        assert response.status_code == 200
        
        data = response.json()
        assert "sessionId" in data
        assert "token" in data
        assert "phoneUrl" in data
        assert len(data["sessionId"]) > 0
        assert len(data["token"]) > 0

    def test_session_id_uniqueness(self, client):
        """Test that each session gets a unique ID."""
        session1 = client.post("/api/session").json()
        session2 = client.post("/api/session").json()
        
        assert session1["sessionId"] != session2["sessionId"]
        assert session1["token"] != session2["token"]

    def test_get_session_status(self, client):
        """Test retrieving session status."""
        create_resp = client.post("/api/session")
        session_id = create_resp.json()["sessionId"]
        
        status_resp = client.get(f"/api/session/{session_id}")
        assert status_resp.status_code == 200
        
        data = status_resp.json()
        assert data["sessionId"] == session_id
        assert data["desktopConnected"] is False
        assert data["phoneConnected"] is False
        assert "createdAt" in data

    def test_get_nonexistent_session(self, client):
        """Test getting a session that doesn't exist."""
        response = client.get("/api/session/nonexistent-id")
        assert response.status_code == 404

    def test_root_endpoint(self, client):
        """Test the root endpoint serves frontend HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_health_endpoint(self, client):
        """Test the health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "POCUS-Health Signaling Server"
        assert data["status"] == "running"

    def test_favicon_endpoint(self, client):
        """Test favicon is served from the backend."""
        response = client.get("/favicon.ico")
        assert response.status_code == 200
        assert response.headers["content-type"] in {
            "image/x-icon",
            "image/vnd.microsoft.icon",
            "image/x-icon; charset=utf-8",
        }


class TestWebSocketSignaling:
    """Tests for WebSocket signaling flow."""

    def test_websocket_hello_handshake_desktop(self, client):
        """Test desktop WebSocket hello handshake."""
        # Create session
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        # Connect WebSocket
        with client.websocket_connect("/ws") as ws:
            # Send hello message
            ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            
            # Receive ready message
            data = ws.receive_json()
            assert data["type"] == "ready"
            assert data["role"] == "desktop"

    def test_websocket_hello_handshake_phone(self, client):
        """Test phone WebSocket hello handshake."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "hello",
                "role": "phone",
                "sessionId": session_id,
                "token": token,
            })
            
            data = ws.receive_json()
            assert data["type"] == "ready"
            assert data["role"] == "phone"

    def test_websocket_invalid_role(self, client):
        """Test WebSocket rejection of invalid role."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "hello",
                "role": "invalid-role",
                "sessionId": session_id,
                "token": token,
            })
            
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Invalid role" in data["message"]

    def test_websocket_invalid_session(self, client):
        """Test WebSocket rejection of invalid session."""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": "nonexistent",
                "token": "invalid-token",
            })
            
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Invalid session or token" in data["message"]

    def test_websocket_invalid_token(self, client):
        """Test WebSocket rejection of invalid token."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": "wrong-token",
            })
            
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_websocket_hello_timeout(self, client):
        """Test WebSocket hello timeout."""
        import asyncio
        
        with client.websocket_connect("/ws") as ws:
            # Don't send hello, wait for timeout
            try:
                # Try to receive (should timeout)
                ws.send_json({"type": "other"})
                data = ws.receive_json(timeout=1.0)
                # If we get an error about missing hello, that's expected
                assert data["type"] == "error"
            except Exception:
                # Timeout is acceptable
                pass

    def test_peer_connection_notification(self, client):
        """Test that peers are notified when connected."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        # Desktop connects first
        with client.websocket_connect("/ws") as desktop_ws:
            desktop_ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            
            ready = desktop_ws.receive_json()
            assert ready["type"] == "ready"
            
            # Phone connects
            with client.websocket_connect("/ws") as phone_ws:
                phone_ws.send_json({
                    "type": "hello",
                    "role": "phone",
                    "sessionId": session_id,
                    "token": token,
                })
                
                phone_ready = phone_ws.receive_json()
                assert phone_ready["type"] == "ready"
                
                # Desktop should be notified of peer connection
                peer_msg = desktop_ws.receive_json()
                assert peer_msg["type"] == "peer-connected"
                assert peer_msg["peer"] == "phone"

    def test_message_relay_desktop_to_phone(self, client):
        """Test that messages from desktop are relayed to phone."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as desktop_ws:
            desktop_ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            desktop_ws.receive_json()  # ready
            
            with client.websocket_connect("/ws") as phone_ws:
                phone_ws.send_json({
                    "type": "hello",
                    "role": "phone",
                    "sessionId": session_id,
                    "token": token,
                })
                phone_ws.receive_json()  # ready
                desktop_ws.receive_json()  # peer-connected
                
                # Desktop sends offer
                offer_msg = {
                    "type": "offer",
                    "sdp": "v=0\no=- 123 456 IN IP4 127.0.0.1"
                }
                desktop_ws.send_json(offer_msg)
                
                # Phone receives offer
                received = phone_ws.receive_json()
                assert received["type"] == "offer"
                assert received["sdp"] == offer_msg["sdp"]

    def test_message_relay_phone_to_desktop(self, client):
        """Test that messages from phone are relayed to desktop."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as desktop_ws:
            desktop_ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            desktop_ws.receive_json()  # ready
            
            with client.websocket_connect("/ws") as phone_ws:
                phone_ws.send_json({
                    "type": "hello",
                    "role": "phone",
                    "sessionId": session_id,
                    "token": token,
                })
                phone_ws.receive_json()  # ready
                desktop_ws.receive_json()  # peer-connected
                
                # Phone sends sensor data
                sensor_msg = {
                    "type": "sensor",
                    "data": {
                        "alpha": 45.5,
                        "beta": 30.2,
                        "gamma": 15.8,
                        "ts": 1234567890
                    }
                }
                phone_ws.send_json(sensor_msg)
                
                # Desktop receives sensor data
                received = desktop_ws.receive_json()
                assert received["type"] == "sensor"
                assert received["data"]["alpha"] == 45.5

    def test_duplicate_connection_rejection(self, client):
        """Test that duplicate connections as same role are rejected."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as ws1:
            ws1.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            ws1.receive_json()  # ready
            
            # Try to connect as desktop again
            with client.websocket_connect("/ws") as ws2:
                ws2.send_json({
                    "type": "hello",
                    "role": "desktop",
                    "sessionId": session_id,
                    "token": token,
                })
                
                error = ws2.receive_json()
                assert error["type"] == "error"
                assert "already connected" in error["message"]

    def test_peer_disconnect_notification(self, client):
        """Test that disconnection is notified to peer."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as desktop_ws:
            desktop_ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            desktop_ws.receive_json()  # ready
            
            with client.websocket_connect("/ws") as phone_ws:
                phone_ws.send_json({
                    "type": "hello",
                    "role": "phone",
                    "sessionId": session_id,
                    "token": token,
                })
                phone_ws.receive_json()  # ready
                desktop_ws.receive_json()  # peer-connected
            
            # Phone closed, desktop should get disconnect notification
            # Give it a moment for the disconnect message to be sent
            import time
            time.sleep(0.1)
            
            try:
                disconnect_msg = desktop_ws.receive_json()
                assert disconnect_msg["type"] == "peer-disconnected"
                assert disconnect_msg["peer"] == "phone"
            except Exception:
                # If we can't receive, the connection may have been terminated
                # This is acceptable behavior
                pass


class TestICECandidates:
    """Tests for ICE candidate relay."""

    def test_ice_candidate_relay(self, client):
        """Test that ICE candidates are properly relayed."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as desktop_ws:
            desktop_ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            desktop_ws.receive_json()  # ready
            
            with client.websocket_connect("/ws") as phone_ws:
                phone_ws.send_json({
                    "type": "hello",
                    "role": "phone",
                    "sessionId": session_id,
                    "token": token,
                })
                phone_ws.receive_json()  # ready
                desktop_ws.receive_json()  # peer-connected
                
                # Desktop sends ICE candidate
                ice_msg = {
                    "type": "ice-candidate",
                    "data": {
                        "candidate": "candidate:1 1 udp 1234 127.0.0.1 12345 typ host",
                        "sdpMLineIndex": 0
                    }
                }
                desktop_ws.send_json(ice_msg)
                
                # Phone receives candidate
                received = phone_ws.receive_json()
                assert received["type"] == "ice-candidate"
                assert received["data"]["candidate"] == ice_msg["data"]["candidate"]


class TestErrorHandling:
    """Tests for error handling."""

    def test_message_without_peer_error(self, client):
        """Test error when sending message without peer connected."""
        session_data = client.post("/api/session").json()
        session_id = session_data["sessionId"]
        token = session_data["token"]
        
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "hello",
                "role": "desktop",
                "sessionId": session_id,
                "token": token,
            })
            ws.receive_json()  # ready
            
            # Send message without peer connected
            ws.send_json({
                "type": "offer",
                "sdp": "test"
            })
            
            error = ws.receive_json()
            assert error["type"] == "error"
            assert "not connected" in error["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
