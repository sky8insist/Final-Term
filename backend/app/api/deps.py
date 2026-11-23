import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from supabase_auth.errors import AuthApiError

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.models.user import CurrentUser
from app.services.observability_service import user_id_context

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase JWT secret is not configured",
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token does not include a user id",
        )

    # Signature/expiry alone cannot revoke a deleted account's existing JWT.
    # Ask Auth on every protected request; never cache account liveness.
    try:
        result = get_supabase_client().auth.get_user(credentials.credentials)
    except AuthApiError as exc:
        code = 401 if exc.status in (401, 403, 404) else 503
        raise HTTPException(status_code=code, detail="Account session unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Account verification unavailable") from exc
    if result.user is None or str(result.user.id) != str(user_id):
        raise HTTPException(status_code=401, detail="Account session unavailable")

    user_id_context.set(user_id)
    return CurrentUser(
        id=user_id,
        email=payload.get("email"),
        role=payload.get("role"),
    )
