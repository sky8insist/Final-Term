from pydantic import BaseModel, EmailStr


class CurrentUser(BaseModel):
    id: str
    email: str | None = None
    role: str | None = None
