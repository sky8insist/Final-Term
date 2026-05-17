from pydantic import BaseModel, EmailStr


class CurrentUser(BaseModel):
    id: str
    email: EmailStr | None = None
    role: str | None = None
