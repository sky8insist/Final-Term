import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_current_user
from app.db.supabase_client import get_supabase_client
from app.models.user import CurrentUser

router = APIRouter()

ACCOUNT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,23}$")
ACCOUNT_EMAIL_DOMAIN = "account.examai.local"


class AccountRegistration(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not ACCOUNT_PATTERN.fullmatch(normalized):
            raise ValueError("账户名需以字母开头，仅包含字母、数字或下划线，长度为 3–24 位")
        return normalized


@router.post("/account/register", status_code=status.HTTP_201_CREATED)
def register_account(payload: AccountRegistration):
    """Create a password account that does not depend on an external mailbox."""
    client = get_supabase_client()
    internal_email = f"{payload.username}@{ACCOUNT_EMAIL_DOMAIN}"
    try:
        result = client.auth.admin.create_user({
            "email": internal_email,
            "password": payload.password,
            "email_confirm": True,
            "user_metadata": {"username": payload.username, "login_type": "account"},
        })
        user = result.user
        if not user:
            raise RuntimeError("Supabase did not return the created user")
        client.table("profiles").insert({"id": str(user.id), "username": payload.username}).execute()
    except Exception as exc:
        message = str(exc).lower()
        if any(marker in message for marker in ("already", "duplicate", "registered", "unique")):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该账户名已被使用") from exc
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="账户注册服务暂时不可用") from exc
    return {"username": payload.username, "loginIdentifier": internal_email}


@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return current_user
