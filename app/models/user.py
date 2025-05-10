from pydantic import BaseModel

class UserUpdateRequest(BaseModel):
    first_name: str
    last_name: str
    role: str