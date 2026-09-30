import hmac
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import settings
from app.errors import ApiError

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="Patient API bearer token")


def require_api_auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    # Fail closed, including in local development. Generate a key with scripts/setup_env.py.
    if not settings.api_bearer_token:
        raise ApiError(503, "auth_not_configured", "Set API_BEARER_TOKEN before accessing patient data")
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not supplied or not hmac.compare_digest(supplied.encode(), settings.api_bearer_token.encode()):
        raise ApiError(401, "unauthorized", "A valid API bearer token is required")
