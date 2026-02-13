from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    _instance = None
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ConnectionManager()
        return cls._instance

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        
        # Clean up broken connections
        for conn in dead_connections:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

manager = ConnectionManager.get_instance()
