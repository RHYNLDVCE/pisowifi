# core/security.py
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Request, HTTPException, status
from jose import JWTError, jwt
import config 

# Load secrets from your secure config
SECRET_KEY = config.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Creates a secure JWT token that expires after a set time.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    
    # Sign the token with your SECRET_KEY
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    """
    Decodes the token to check if it is valid and not expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def is_admin(request: Request) -> bool:
    """
    Dependency to protect admin routes.
    Checks if the user has a valid, unexpired 'admin_token' cookie.
    """
    token = request.cookies.get("admin_token")
    
    # 1. Check if cookie exists
    if not token:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND, 
            headers={"Location": "/login"}
        )
    
    # 2. Verify the token signature and expiration
    payload = verify_token(token)
    
    # 3. Security Check: Ensure token is valid and belongs to the admin
    if not payload or payload.get("sub") != config.ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND, 
            headers={"Location": "/login"}
        )

    return True