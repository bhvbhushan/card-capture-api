from app.services.sftp_service import (
    create_or_update_sftp_config_service,
    test_sftp_connection_service,
    get_sftp_config_service
)
from typing import Dict, Any


async def create_or_update_sftp_config_controller(payload: Dict[str, Any], user: Dict[str, Any]):
    """
    Controller for creating or updating SFTP configuration
    """
    return await create_or_update_sftp_config_service(payload, user)


async def test_sftp_connection_controller(payload: Dict[str, Any], user: Dict[str, Any]):
    """
    Controller for testing SFTP connection
    """
    return await test_sftp_connection_service(payload, user)


async def get_sftp_config_controller(school_id: str, user: Dict[str, Any]):
    """
    Controller for getting SFTP configuration
    """
    return await get_sftp_config_service(school_id, user) 