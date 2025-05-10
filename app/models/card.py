from pydantic import BaseModel
from typing import List

class MarkExportedPayload(BaseModel):
    document_ids: List[str]

class ArchiveCardsPayload(BaseModel):
    document_ids: List[str]

class DeleteCardsPayload(BaseModel):
    document_ids: List[str] 