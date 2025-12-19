import os
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    stream_type: Literal["livekit"] = Field(
        default="livekit", description="Stream type (livekit)"
    )
    livekit_url: str = Field(default=os.getenv("LIVEKIT_URL"), description="Livekit URL")
    livekit_token: str = Field(
        ...,
        description="Livekit token (must be minted per session with API key/secret)",
    )
    audio_only_from_data_stream: bool = Field(
        default=True, description="Whether to only publish audio from the data stream"
    )


class SourceData(BaseModel):
    docs: Optional[list[dict[str, str]]] = Field(default=None, description="Documents to ingest")
    urls: Optional[list[str]] = Field(default=None, description="URLs to crawl")
    voice_id: Optional[str] = Field(default=None, description="Voice ID override")
    prologue: Optional[str] = Field(default=None, description="Prologue text")
    prompt: Optional[str] = Field(default=None, description="Prompt text")
    background_url: Optional[str] = Field(default=None, description="Background URL")
    language: Optional[str] = Field(default=None, description="Language code")
    mode_type: Optional[int] = Field(default=None, description="1: Retelling, 2: Dialogue")
    scene_mode: Literal["meeting"] = Field(
        default="meeting",
        description="Scene mode, receive audio and only do lipsync, then send audio and video",
    )
