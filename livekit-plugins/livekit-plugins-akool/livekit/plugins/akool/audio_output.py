from __future__ import annotations

import asyncio
from typing import Any

from livekit import rtc
from livekit.agents import utils
from livekit.agents.voice import io

from .log import logger


class AvatarTrackAudioOutput(io.AudioOutput):
    """
    AudioOutput implementation that publishes audio via LiveKit audio track,
    restricted to only allow subscription by a specific avatar participant.
    只允许指定的 avatar 参与者订阅的音频轨道输出实现。
    """

    def __init__(
        self,
        room: rtc.Room,
        *,
        destination_identity: str,
        sample_rate: int,
        num_channels: int = 1,
        track_name: str = "avatar_audio",
        queue_size_ms: int = 100_000,
        wait_remote_track: rtc.TrackKind.ValueType | None = None,
    ) -> None:
        super().__init__(label="AvatarTrackAudioOutput", next_in_chain=None, sample_rate=sample_rate)
        self._room = room
        self._destination_identity = destination_identity
        self._track_name = track_name
        self._num_channels = num_channels
        self._wait_remote_track = wait_remote_track

        self._audio_source = rtc.AudioSource(sample_rate, num_channels, queue_size_ms)
        self._publication: rtc.LocalTrackPublication | None = None
        self._track_sid: str | None = None

        self._lock = asyncio.Lock()
        self._started = False
        self._start_atask: asyncio.Task[Any] | None = None

        self._pushed_duration: float = 0.0
        self._flush_task: asyncio.Task[None] | None = None
        self._interrupted_event = asyncio.Event()

        # 用于处理房间连接状态
        self._room_connected_fut = asyncio.Future[None]()
        self._room.on("connection_state_changed", self._handle_connection_state_changed)
        if self._room.isconnected():
            self._room_connected_fut.set_result(None)

    def _handle_connection_state_changed(self, state: rtc.ConnectionState) -> None:
        if self._room.isconnected() and not self._room_connected_fut.done():
            self._room_connected_fut.set_result(None)

    @utils.log_exceptions(logger=logger)
    async def _start_task(self) -> None:
        """Initialize and publish the audio track with restricted permissions."""
        async with self._lock:
            if self._started:
                return

            await self._room_connected_fut

            # 等待目标参与者（avatar）加入房间
            logger.debug(
                "waiting for avatar participant",
                extra={"identity": self._destination_identity},
            )
            await utils.wait_for_participant(room=self._room, identity=self._destination_identity)

            # 如果需要等待远程轨道（例如视频轨道）
            if self._wait_remote_track:
                logger.debug(
                    "waiting for remote track from avatar",
                    extra={
                        "identity": self._destination_identity,
                        "kind": rtc.TrackKind.Name(self._wait_remote_track),
                    },
                )
                await utils.wait_for_track_publication(
                    room=self._room,
                    identity=self._destination_identity,
                    kind=self._wait_remote_track,
                )

            # 创建并发布音频轨道
            track = rtc.LocalAudioTrack.create_audio_track(self._track_name, self._audio_source)
            publish_options = rtc.TrackPublishOptions(
                source=rtc.TrackSource.SOURCE_MICROPHONE,
            )
            self._publication = await self._room.local_participant.publish_track(
                track, publish_options
            )
            self._track_sid = self._publication.sid

            logger.info(
                f"Audio track published with sid: {self._track_sid}, "
                f"restricted to avatar: {self._destination_identity}"
            )

            # 设置轨道订阅权限：只允许 avatar 参与者订阅
            # Set track subscription permissions: only allow avatar participant to subscribe
            self._room.local_participant.set_track_subscription_permissions(
                allow_all_participants=False,
                participant_permissions=[
                    rtc.ParticipantTrackPermission(
                        participant_identity=self._destination_identity,
                        allow_all=False,
                        allowed_track_sids=[self._track_sid],
                    )
                ],
            )
            logger.debug(
                f"Track subscription permissions set: only {self._destination_identity} can subscribe"
            )

            # 等待订阅完成
            await self._publication.wait_for_subscription()
            logger.debug("Avatar participant subscribed to audio track")

            self._started = True

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        """Capture and stream audio frame via the published track."""
        # 确保启动任务已创建
        if self._start_atask is None:
            self._start_atask = asyncio.create_task(self._start_task())

        # 等待启动完成
        await asyncio.shield(self._start_atask)

        await super().capture_frame(frame)

        if self._flush_task and not self._flush_task.done():
            logger.warning("capture_frame called while flush is in progress")
            await self._flush_task

        self._pushed_duration += frame.duration
        await self._audio_source.capture_frame(frame)

    def flush(self) -> None:
        """Flush the audio buffer and wait for playout."""
        super().flush()

        if not self._pushed_duration:
            return

        if self._flush_task and not self._flush_task.done():
            logger.warning("flush called while playback is in progress")
            self._flush_task.cancel()

        self._flush_task = asyncio.create_task(self._wait_for_playout())

    def clear_buffer(self) -> None:
        """Clear the audio buffer, stopping playback immediately."""
        if not self._pushed_duration:
            return
        self._interrupted_event.set()

    async def _wait_for_playout(self) -> None:
        """Wait for audio playout to complete or be interrupted."""
        wait_for_interruption = asyncio.create_task(self._interrupted_event.wait())
        wait_for_playout = asyncio.create_task(self._audio_source.wait_for_playout())
        await asyncio.wait(
            [wait_for_playout, wait_for_interruption],
            return_when=asyncio.FIRST_COMPLETED,
        )

        interrupted = wait_for_interruption.done()
        pushed_duration = self._pushed_duration

        if interrupted:
            pushed_duration = max(pushed_duration - self._audio_source.queued_duration, 0)
            self._audio_source.clear_queue()
            wait_for_playout.cancel()
        else:
            wait_for_interruption.cancel()

        self._pushed_duration = 0
        self._interrupted_event.clear()
        self.on_playback_finished(playback_position=pushed_duration, interrupted=interrupted)

    async def aclose(self) -> None:
        """Close the audio output and cleanup resources."""
        self._room.off("connection_state_changed", self._handle_connection_state_changed)

        if self._flush_task:
            await utils.aio.cancel_and_wait(self._flush_task)
        if self._start_atask:
            await utils.aio.cancel_and_wait(self._start_atask)

        # 取消发布轨道
        if self._publication and self._room.isconnected():
            await self._room.local_participant.unpublish_track(self._publication.sid)

        await self._audio_source.aclose()
        logger.debug("Avatar audio output closed")
