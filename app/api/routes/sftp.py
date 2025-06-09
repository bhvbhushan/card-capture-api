from fastapi import APIRouter, Depends
from app.controllers.sftp_controller import (
    create_or_update_sftp_config_controller,
    test_sftp_connection_controller,
    get_sftp_config_controller
)
from app.core.auth import get_current_user
from typing import Dict, Any

router = APIRouter(tags=["SFTP"])


@router.post("/config")
async def create_or_update_sftp_config(
    payload: Dict[str, Any],
    user=Depends(get_current_user)
):
    """
    Create or update SFTP configuration for a school
    
    Request body:
    {
        "school_id": "uuid",
        "host": "ft.technolutions.net",
        "port": 22,
        "username": "username",
        "password": "password",
        "remote_path": "/path/to/uploads",
        "enabled": true
    }
    """
    return await create_or_update_sftp_config_controller(payload, user)


@router.post("/test")
async def test_sftp_connection(
    payload: Dict[str, Any],
    user=Depends(get_current_user)
):
    """
    Test SFTP connection with provided credentials
    
    Request body:
    {
        "school_id": "uuid",  // optional, for permission checking
        "host": "ft.technolutions.net",
        "port": 22,
        "username": "username", 
        "password": "password",
        "remote_path": "/path/to/test"  // optional, defaults to "/"
    }
    """
    return await test_sftp_connection_controller(payload, user)


@router.get("/config/{school_id}")
async def get_sftp_config(
    school_id: str,
    user=Depends(get_current_user)
):
    """
    Get SFTP configuration for a school
    
    Note: Password will not be returned for security reasons.
    Response will include a boolean indicating if password is configured.
    """
    return await get_sftp_config_controller(school_id, user) 