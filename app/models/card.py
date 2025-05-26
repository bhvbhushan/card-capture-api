from pydantic import BaseModel, Field
from typing import List, Optional

class BulkActionPayload(BaseModel):
    """Standardized payload for all bulk card actions"""
    document_ids: List[str]
    review_status: Optional[str] = None
    status: Optional[str] = None

# Legacy models for backward compatibility during transition
class MarkExportedPayload(BaseModel):
    document_ids: Optional[List[str]] = Field(None, alias='documentIds')
    documentIds: Optional[List[str]] = None
    ids: Optional[List[str]] = None
    
    def get_document_ids(self) -> List[str]:
        """Get document IDs from any of the possible field names"""
        return self.document_ids or self.documentIds or self.ids or []

class ArchiveCardsPayload(BaseModel):
    document_ids: List[str]
    status: str
    review_status: str

class DeleteCardsPayload(BaseModel):
    document_ids: List[str]

class MoveCardsPayload(BaseModel):
    document_ids: List[str]
    status: str = "reviewed" 