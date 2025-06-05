from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class SchoolCreate(BaseModel):
    name: str
    docai_processor_id: Optional[str] = None

class SchoolResponse(BaseModel):
    id: str
    name: str
    docai_processor_id: Optional[str]
    created_at: datetime
    user_count: int

class SuperAdminCheck(BaseModel):
    is_superadmin: bool
    user_id: str

class InviteAdminRequest(BaseModel):
    email: str  # Using str instead of EmailStr to avoid email-validator dependency issues
    first_name: str
    last_name: str
    school_id: str 