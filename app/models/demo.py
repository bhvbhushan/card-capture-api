from pydantic import BaseModel, EmailStr
from typing import Optional

class DemoRequest(BaseModel):
    name: str
    email: EmailStr
    university: str
    enrollment: Optional[str] = None
    message: Optional[str] = None 