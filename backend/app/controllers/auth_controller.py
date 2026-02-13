import secrets
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config_controller import ConfigManager
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

class AuthHandler:
    _instance = None
    
    def __init__(self):
        self._tokens = set() # Simple in-memory token store
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = AuthHandler()
        return cls._instance

    def verify_password(self, password: str) -> bool:
        """Verify the provided password against config."""
        config_pass = ConfigManager.get_instance().panel_password
        if not config_pass:
            # If no password set, always allow? 
            # Or should we disable login endpoint if no password?
            # User wants to "set access password", so if set, verify.
            return True
            
        # Constant time comparison not strictly necessary for this scale but good practice
        return password == config_pass

    def create_token(self) -> str:
        """Generate a session token."""
        token = secrets.token_hex(32)
        self._tokens.add(token)
        return token

    def revoke_token(self, token: str):
        if token in self._tokens:
            self._tokens.remove(token)

    async def get_current_user(self, request: Request, creds: HTTPAuthorizationCredentials = Security(security)):
        """Dependency for protected endpoints."""
        config_pass = ConfigManager.get_instance().panel_password
        
        # If no password configured, authentication is disabled
        if not config_pass:
            return "admin"

        if not creds:
             # Check for query param 'token' for WebSocket or quick access if needed, 
             # but strictly standard is header.
             raise HTTPException(status_code=401, detail="Not authenticated")

        token = creds.credentials
        if token not in self._tokens:
            raise HTTPException(status_code=401, detail="Invalid token")
            
        return "admin"
