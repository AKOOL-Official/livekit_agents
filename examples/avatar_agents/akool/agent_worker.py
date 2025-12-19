import asyncio
import logging
import os

from dotenv import load_dotenv
from openai.types.beta.realtime.session import TurnDetection

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    WorkerType,
    cli,
)
from livekit.plugins import akool, openai
from livekit.plugins.akool.schema import SourceData

logger = logging.getLogger("akool-avatar-example")
logger.setLevel(logging.INFO)

load_dotenv()


async def entrypoint(ctx: JobContext):
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            model="gpt-4o-realtime-preview",
            voice="alloy",
            turn_detection=TurnDetection(
                type="server_vad",
                threshold=0.7,
                prefix_padding_ms=300,
                silence_duration_ms=1000,
                create_response=True,
                interrupt_response=True,
            ),
        ),
    )

    akool_avatar = akool.AvatarSession(
        avatar_id=os.getenv("AKOOL_AVATAR_ID", "dvp_Tristan_cloth2_1080P"),
    )

    source_data = SourceData(
        voice_id="690c93c10274695d7c5e5ed4",
        language="en",
        mode_type=2,
    )

    try:
        logger.info(f"Starting avatar session for room {ctx.room.name}")
        await akool_avatar.start(session, room=ctx.room, source_data=source_data)

        # 监听用户断开连接事件
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            logger.info(f"Participant {participant.identity} disconnected")
            # Only one participant left, close session
            remote_participants = [a.identity for a in ctx.room.remote_participants.values()]
            if (
                len(remote_participants) == 1
                and akool_avatar.get_avatar_participant_identity() == remote_participants[0]
            ):
                logger.info("Closing avatar session")
                asyncio.create_task(akool_avatar.aclose())

        ctx.room.on("participant_disconnected", on_participant_disconnected)

        # start the agent, it will join the room and wait for the avatar to join
        await session.start(
            agent=Agent(instructions="Talk to me!"),
            room=ctx.room,
        )

        session.generate_reply(instructions="say hello to the user")

    except Exception as e:
        logger.error(f"Error in entrypoint: {e}")
        # Ensure cleanup resources when error occurs
        await akool_avatar.aclose()
        raise


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, worker_type=WorkerType.ROOM))
