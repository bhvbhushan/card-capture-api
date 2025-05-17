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

async def get_cards_controller(event_id: Union[str, None] = None):
    return await get_cards_service(event_id)

async def mark_as_exported_controller(payload: MarkExportedPayload):
    return await mark_as_exported_service(payload)

async def archive_cards_controller(payload: ArchiveCardsPayload):
    return await archive_cards_service(payload)

async def delete_cards_controller(payload: DeleteCardsPayload):
    return await delete_cards_service(payload)

async def move_cards_controller(payload: MoveCardsPayload):
    return await move_cards_service(payload) 