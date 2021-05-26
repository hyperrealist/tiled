from datetime import datetime, timedelta
from tiled.server.models import AccessAndRefreshTokens, RefreshToken
from typing import Any, Optional
import uuid
import warnings

from fastapi import (
    Depends,
    APIRouter,
    HTTPException,
    Security,
    Request,
    Response,
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.security.api_key import APIKeyCookie, APIKeyQuery, APIKeyHeader

# To hide third-party warning
# .../jose/backends/cryptography_backend.py:18: CryptographyDeprecationWarning:
#     int_from_bytes is deprecated, use int.from_bytes instead
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel, BaseSettings

from .settings import get_settings
from ..utils import SpecialUsers

ALGORITHM = "HS256"
UNIT_SECOND = timedelta(seconds=1)
API_KEY_COOKIE_NAME = "tiled_api_key"
API_KEY_HEADER_NAME = "x-tiled-api-key"
API_KEY_QUERY_PARAMETER = "api_key"
CSRF_COOKIE_NAME = "tiled_csrf"


def get_authenticator():
    raise NotImplementedError(
        "This should be overridden via dependency_overrides. "
        "See tiled.server.app.serve_catalog()."
    )


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)
api_key_cookie = APIKeyCookie(name="tiled_api_key", auto_error=False)
authentication_router = APIRouter()


def create_access_token(data: dict, expires_delta, secret_key):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    data: dict, secret_key, session_id=None, session_creation_time=None
):
    to_encode = data.copy()
    issued_at_time = datetime.utcnow()
    session_id = session_id or uuid.uuid4().int
    session_creation_time = session_creation_time or issued_at_time
    to_encode.update(
        {
            "type": "refresh",
            # This is used to compute expiry.
            # We do not use "exp" in refresh tokens because we want the freedom
            # to adjust the max age and have that respected immediately.
            "iat": issued_at_time.timestamp(),
            # The session ID is the same for a whole chain of refresh tokens,
            # and it can be potentially used to revoke all of them if
            # we believe the session is compromised.
            "sid": session_id,
            # This is used to enforce a maximum session age.
            "sct": session_creation_time.timestamp(),  # nonstandard claim
        }
    )
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token, secret_keys, expected_type):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # The first key in settings.secret_keys is used for *encoding*.
    # All keys are tried for *decoding* until one works or they all
    # fail. They supports key rotation.
    for secret_key in secret_keys:
        try:
            payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
            break
        except ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Access token has expired.")
        except JWTError:
            # Try the next key in the key rotation.
            continue
    else:
        raise credentials_exception
    if payload.get("type") != expected_type:
        raise credentials_exception
    return payload


async def check_single_user_api_key(
    api_key_query: str = Security(api_key_query),
    api_key_header: str = Security(api_key_header),
    api_key_cookie: str = Security(api_key_cookie),
    settings: BaseSettings = Depends(get_settings),
):
    for api_key in [api_key_query, api_key_header, api_key_cookie]:
        if api_key is not None:
            if api_key == settings.single_user_api_key:
                return True
            raise HTTPException(status_code=401, detail="Invalid API key")
    return False


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    has_single_user_api_key: str = Depends(check_single_user_api_key),
    settings: BaseSettings = Depends(get_settings),
    authenticator=Depends(get_authenticator),
):
    if (authenticator is None) and has_single_user_api_key:
        if request.cookies.get(API_KEY_COOKIE_NAME) != settings.single_user_api_key:
            request.state.cookies_to_set.append(
                (API_KEY_COOKIE_NAME, settings.single_user_api_key)
            )
        return SpecialUsers.admin
    if token is None:
        if settings.allow_anonymous_access:
            # Any user who can see the server can make unauthenticated requests.
            # This is a sentinel that has special meaning to the authorization
            # code (the access control policies).
            return SpecialUsers.public
        else:
            # In this mode, there may still be entries that are visible to all,
            # but users have to authenticate as *someone* to see anything.
            raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token, settings.secret_keys, "access")
    username: str = payload.get("sub")
    return username


@authentication_router.post("/token", response_model=AccessAndRefreshTokens)
async def login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    authenticator: Any = Depends(get_authenticator),
    settings: BaseSettings = Depends(get_settings),
):
    if authenticator is None:
        if settings.allow_anonymous_access:
            msg = "This is a public Tiled server with no login."
        else:
            msg = (
                "This is a single-user Tiled server. "
                "To authenticate, use the API key logged at server startup."
            )
        raise HTTPException(status_code=404, detail=msg)
    username = authenticator.authenticate(
        username=form_data.username, password=form_data.password
    )
    if not username:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": username},
        expires_delta=settings.access_token_max_age,
        secret_key=settings.secret_keys[0],  # Use the *first* secret key to encode.
    )
    refresh_token = create_refresh_token(
        data={"sub": username},
        secret_key=settings.secret_keys[0],  # Use the *first* secret key to encode.
    )
    return {
        "access_token": access_token,
        "expires_in": settings.access_token_max_age / UNIT_SECOND,
        "refresh_token": refresh_token,
        "refresh_token_expires_in": settings.refresh_token_max_age / UNIT_SECOND,
        "token_type": "bearer",
    }


@authentication_router.post("/token/refresh", response_model=AccessAndRefreshTokens)
async def refresh(
    refresh_token: RefreshToken,
    settings: BaseSettings = Depends(get_settings),
):
    "Obtain a new access token and refresh token."
    payload = decode_token(refresh_token.refresh_token, settings.secret_keys, "refresh")
    now = datetime.utcnow().timestamp()
    # Enforce refresh token max age.
    # We do this here rather than with an "exp" claim in the token so that we can
    # change the configuration and have that change respected.
    if timedelta(seconds=(now - payload["iat"])) > settings.refresh_token_max_age:
        raise HTTPException(
            status_code=401, detail="Session has expired. Please re-authenticate."
        )
    # Enforce maximum session age, if set.
    if settings.session_max_age is not None:
        if timedelta(seconds=(now - payload["sct"])) > settings.session_max_age:
            raise HTTPException(
                status_code=401, detail="Session has expired. Please re-authenticate."
            )
    new_refresh_token = create_refresh_token(
        data={"sub": payload["sub"]},
        session_id=payload["sid"],
        session_creation_time=datetime.fromtimestamp(payload["sct"]),
        secret_key=settings.secret_keys[0],  # Use the *first* secret key to encode.
    )
    access_token = create_access_token(
        data={"sub": payload["sub"]},
        expires_delta=settings.access_token_max_age,
        secret_key=settings.secret_keys[0],  # Use the *first* secret key to encode.
    )
    return {
        "access_token": access_token,
        "expires_in": settings.access_token_max_age / UNIT_SECOND,
        "refresh_token": new_refresh_token,
        "refresh_token_expires_in": settings.refresh_token_max_age / UNIT_SECOND,
        "token_type": "bearer",
    }


@authentication_router.post("/logout")
async def logout(
    response: Response,
):
    response.delete_cookie(API_KEY_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    return {}
