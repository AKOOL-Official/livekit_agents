import logging
import os

from dotenv import load_dotenv

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, WorkerType, cli
from livekit.plugins import openai, akool

logger = logging.getLogger("akool-avatar-example")
logger.setLevel(logging.INFO)

load_dotenv()


async def entrypoint(ctx: JobContext):
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            voice="alloy",
            modalities=["audio"],  # 只输出音频，不输出文本
        ),
    )

    akool_avatar = akool.AvatarSession(
        avatar_config=akool.AvatarConfig(avatar_id="dvp_Tristan_cloth2_1080P"),
        client_id=os.getenv("AKOOL_CLIENT_ID"),
        client_secret=os.getenv("AKOOL_CLIENT_SECRET"),
    )
    await akool_avatar.start(session, room=ctx.room)

    # start the agent, it will join the room and wait for the avatar to join
    await session.start(
        agent=Agent(instructions="Talk to me!"),
        room=ctx.room,
    )

    session.generate_reply(instructions="say hello to the user")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, worker_type=WorkerType.ROOM))
