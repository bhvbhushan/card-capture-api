from app.services.cards_service import (
    get_cards_service,
    mark_as_exported_service,
    archive_cards_service,
    delete_cards_service,
    move_cards_service
)
from app.models.card import (
    MarkExportedPayload,
    ArchiveCardsPayload,
    DeleteCardsPayload,
    MoveCardsPayload
)
from typing import Union
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from app.utils.archive_logging import log_archive_debug

async def get_cards_controller(event_id: Union[str, None] = None):
    return await get_cards_service(event_id)

async def mark_as_exported_controller(payload: MarkExportedPayload):
    document_ids = payload.get_document_ids()
    print(f"📤 Mark as exported controller received payload: {payload.dict()}")
    print(f"📤 Document IDs: {document_ids}")
    print(f"📤 Number of document IDs: {len(document_ids)}")
    
    # Create a simple payload object for the service
    class SimplePayload:
        def __init__(self, document_ids):
            self.document_ids = document_ids
    
    simple_payload = SimplePayload(document_ids)
    return await mark_as_exported_service(simple_payload)

async def archive_cards_controller(payload):
    log_archive_debug("=== ARCHIVE CARDS CONTROLLER START ===")
    log_archive_debug("Received payload", payload.dict())
    
    try:
        result = await archive_cards_service(payload.document_ids)
        
        if "error" in result:
            log_archive_debug(f"Error in service layer: {result['error']}")
            return JSONResponse(
                status_code=500,
                content={"error": result["error"]}
            )
        
        log_archive_debug("Service layer result", result)
        log_archive_debug("=== ARCHIVE CARDS CONTROLLER END ===")
        
        return JSONResponse(
            status_code=200,
            content=result
        )
    except Exception as e:
        error_msg = f"Error in controller: {str(e)}"
        log_archive_debug(f"Error: {error_msg}")
        log_archive_debug("=== ARCHIVE CARDS CONTROLLER END WITH ERROR ===")
        return JSONResponse(
            status_code=500,
            content={"error": error_msg}
        )

async def delete_cards_controller(payload: DeleteCardsPayload):
    return await delete_cards_service(payload)

async def move_cards_controller(payload: MoveCardsPayload):
    return await move_cards_service(payload) 