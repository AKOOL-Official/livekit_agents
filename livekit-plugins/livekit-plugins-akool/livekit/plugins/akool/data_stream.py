import math

from livekit import rtc
from livekit.agents.voice.avatar import DataStreamAudioOutput

# 默认 20ms 的 chunk 大小
DEFAULT_CHUNK_SIZE_MS = 20
# 剩余数据小于此阈值时，合并到前一个 chunk（毫秒）
MERGE_THRESHOLD_MS = 5


class ChunkDataStreamAudioOutput(DataStreamAudioOutput):
    """
    DataStreamAudioOutput 的扩展实现，将音频数据切分为固定大小的 chunk（默认 20ms）后再发送。
    如果剩余数据太小（< 5ms），会合并到前一个 chunk 一起发送。
    """

    def __init__(
        self,
        room: rtc.Room,
        *,
        destination_identity: str,
        sample_rate: int | None = None,
        wait_remote_track: rtc.TrackKind.ValueType | None = None,
        chunk_size_ms: int = DEFAULT_CHUNK_SIZE_MS,
        merge_threshold_ms: int = MERGE_THRESHOLD_MS,
    ):
        super().__init__(
            room,
            destination_identity=destination_identity,
            sample_rate=sample_rate,
            wait_remote_track=wait_remote_track,
        )
        self._chunk_size_ms = chunk_size_ms
        self._merge_threshold_ms = merge_threshold_ms
        self._buf = bytearray()
        self._frame_sample_rate: int = 0
        self._frame_num_channels: int = 0

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        """将音频数据切分为 20ms 的 chunk 后发送，小数据合并到前一个 chunk"""
        # 保存音频参数
        self._frame_sample_rate = frame.sample_rate
        self._frame_num_channels = frame.num_channels

        # 计算字节数
        bytes_per_sample = 2 * frame.num_channels  # int16 * channels
        bytes_per_chunk = int(math.ceil(frame.sample_rate * self._chunk_size_ms / 1000)) * bytes_per_sample
        bytes_threshold = int(math.ceil(frame.sample_rate * self._merge_threshold_ms / 1000)) * bytes_per_sample

        # 添加数据到缓冲区
        self._buf.extend(frame.data)

        # 切分并发送
        while len(self._buf) >= bytes_per_chunk:
            remaining_after = len(self._buf) - bytes_per_chunk

            # 如果剩余数据小于阈值，合并到当前 chunk
            if 0 < remaining_after < bytes_threshold:
                chunk_data = bytes(self._buf)
                self._buf.clear()
            else:
                chunk_data = bytes(self._buf[:bytes_per_chunk])
                self._buf = self._buf[bytes_per_chunk:]

            chunk_frame = rtc.AudioFrame(
                data=chunk_data,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                samples_per_channel=len(chunk_data) // bytes_per_sample,
            )
            await super().capture_frame(chunk_frame)
