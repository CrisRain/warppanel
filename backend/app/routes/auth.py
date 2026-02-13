from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..controllers.auth_controller import AuthHandler

router = APIRouter()
auth_handler = AuthHandler.get_instance()

class LoginRequest(BaseModel):
    password: str

@router.post("/login")
async def login(req: LoginRequest):
    if auth_handler.verify_password(req.password):
        token = auth_handler.create_token()
        return {"success": True, "token": token}
    raise HTTPException(status_code=401, detail="Invalid password")

@router.get("/check")
async def check_auth(user: str = Depends(auth_handler.get_current_user)):
    return {"authenticated": True, "user": user}
