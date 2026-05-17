from pydantic import BaseModel


class Subject(BaseModel):
    id: str
    user_id: str
    name: str
    description: str | None = None
