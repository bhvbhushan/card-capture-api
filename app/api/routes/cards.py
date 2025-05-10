from fastapi import APIRouter, Body
from typing import Union, List, Dict, Any
from app.controllers.cards_controller import (
    get_cards_controller,
    archive_cards_controller,
    mark_as_exported_controller,
    delete_cards_controller
)
from app.models.card import ArchiveCardsPayload, MarkExportedPayload, DeleteCardsPayload

router = APIRouter(tags=["Cards"])

@router.get("/cards", response_model=List[Dict[str, Any]])
async def get_cards(event_id: Union[str, None] = None):
    return await get_cards_controller(event_id)

@router.post("/archive-cards")
async def archive_cards(payload: ArchiveCardsPayload):
    return await archive_cards_controller(payload)

@router.post("/mark-exported")
async def mark_as_exported(payload: MarkExportedPayload):
    return await mark_as_exported_controller(payload)

@router.post("/delete-cards")
async def delete_cards(payload: DeleteCardsPayload):
    return await delete_cards_controller(payload) 