from pydantic import BaseModel
from typing import List

class UserUpdateRequest(BaseModel):
    first_name: str
    last_name: str
    role: List[str]