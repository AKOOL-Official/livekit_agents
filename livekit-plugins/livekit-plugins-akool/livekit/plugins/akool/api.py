import asyncio
import os
from typing import Any, Optional

import aiohttp

from livekit import api
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    NotGivenOr,
)

from .log import logger
from .schema import Credentials, SourceData


class AkoolException(Exception):
    """Exception for Akool errors"""


class AkoolAPI:
    def __init__(
        self,
        avatar_id: str,
        *,
        router_url: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._avatar_id = avatar_id
        # Router that orchestrates worker /lock_session and /unlock_session calls
        self._router_url = router_url or os.getenv("AKOOL_ROUTER_URL")
        self._conn_options = conn_options
        self._session = session or aiohttp.ClientSession()

    async def create_session(
        self,
        *,
        credentials: Credentials,
        source_data: Optional[SourceData] = None,
        avatar_id: Optional[str] = None,
        stream_type: str = "livekit",
    ) -> str:
        """
        Call the deployed session router /create_session (LiveKit path).
        Expects router to route to worker /lock_session and return a session id.
        """
        if not self._router_url:
            raise AkoolException("AKOOL_ROUTER_URL must be set for router-based session management")

        url = f"{self._router_url}/create_session"
        payload: dict[str, Any] = {
            "stream_type": stream_type,  # livekit only
            "server_credentials": credentials.model_dump(exclude_none=True),
            "avatar_id": avatar_id or self._avatar_id,
        }
        if source_data:
            payload["source_data"] = source_data.model_dump(exclude_none=True)

        # Avoid logging sensitive tokens
        token_preview = f"{credentials.livekit_token[:6]}...len={len(credentials.livekit_token)}"
        logger.debug(
            "create_session payload prepared (credentials redacted)",
            extra={
                "livekit_url": credentials.livekit_url,
                "token_preview": token_preview,
            },
        )
        response_data = await self._post(url, payload)
        logger.info("create_session response received")
        return response_data.get("id") or response_data.get("data")  # router returns { id, ... }

    async def close_session(self, session_id: str) -> None:
        """
        Close avatar session via router /close_session.
        """
        if not self._router_url:
            raise AkoolException("AKOOL_ROUTER_URL must be set for router-based session management")

        url = f"{self._router_url}/close_session"
        payload = {"session_id": session_id}
        logger.info("close_session payload prepared")
        response_data = await self._post(url, payload)
        logger.info("close_session response received")

    @staticmethod
    def mint_livekit_token(
        *,
        room_name: str,
        identity: str,
        name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ) -> str:
        """
        Mint a LiveKit JWT for room join. Tokens must be created per session; do not store in env.
        """
        lk_api_key = api_key or os.getenv("LIVEKIT_API_KEY")
        lk_api_secret = api_secret or os.getenv("LIVEKIT_API_SECRET")
        if not lk_api_key or not lk_api_secret:
            raise AkoolException("LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required to mint tokens")

        token = (
            api.AccessToken(api_key=lk_api_key, api_secret=lk_api_secret)
            .with_identity(identity)
            .with_name(name or identity)
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        return token

    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Make a POST request to the Akool API with retry logic.

        Args:
            endpoint: API endpoint path (without leading slash)
            payload: JSON payload for the request

        Returns:
            Response data as a dictionary

        Raises:
            APIConnectionError: If the request fails after all retries
        """
        headers = {"Content-Type": "application/json"}

        for i in range(self._conn_options.max_retry):
            try:
                async with self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(sock_connect=self._conn_options.timeout),
                ) as response:
                    if not response.ok:
                        text = await response.text()
                        raise APIStatusError(
                            "Server returned an error", status_code=response.status, body=text
                        )
                    return await response.json()  # type: ignore
            except Exception as e:
                if isinstance(e, APIConnectionError):
                    logger.warning("failed to call akool api", extra={"error": str(e)})
                else:
                    logger.exception("failed to call akool api")

                if i < self._conn_options.max_retry - 1:
                    await asyncio.sleep(self._conn_options.retry_interval)

        raise APIConnectionError("Failed to call Akool API after all retries")
