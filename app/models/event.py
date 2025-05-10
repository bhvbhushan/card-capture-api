from pydantic import BaseModel
from typing import Optional, List

class EventCreatePayload(BaseModel):
    name: str
    date: str
    school_id: str

class EventUpdatePayload(BaseModel):
    name: Optional[str] = None
    date: Optional[str] = None
    school_id: Optional[str] = None
    status: Optional[str] = None

class ArchiveEventsPayload(BaseModel):
    event_ids: List[str] 