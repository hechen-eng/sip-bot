from dotenv import load_dotenv
import json
from livekit import api
from livekit import agents, rtc
from livekit.agents import AgentServer,AgentSession, Agent, room_io
from livekit.plugins import noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(".env.local")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
            You eagerly assist users with their questions by providing information from your extensive knowledge.
            Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
            You are curious, friendly, and have a sense of humor.""",
        )

server = AgentServer()

@server.rtc_session(agent_name="hechen-bot2")
async def my_agent(ctx: agents.JobContext):
    # If a phone number was provided in job metadata, place an outbound call.
    # In console mode (or when metadata is empty), skip and run as a normal voice session.
    phone_number = None
    metadata = getattr(ctx.job, "metadata", None) or ""
    if metadata.strip():
        dial_info = json.loads(metadata)
        phone_number = dial_info["phone_number"]

    # The participant's identity can be anything you want, but this example uses the phone number itself
    sip_participant_identity = phone_number
    if phone_number is not None:
        # The outbound call will be placed after this method is executed
        try:
            await ctx.api.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                # This ensures the participant joins the correct room
                room_name=ctx.room.name,

                # This is the outbound trunk ID to use (i.e. which phone number the call will come from)
                # You can get this from LiveKit CLI with `lk sip outbound list`
                sip_trunk_id='ST_wJ7K3e964ow5',

                # The outbound phone number to dial and identity to use
                sip_call_to=phone_number,
                participant_identity=sip_participant_identity,

                # This will wait until the call is answered before returning
                wait_until_answered=True,
            ))

            print("call picked up successfully")
        except api.TwirpError as e:
            print(f"error creating SIP participant: {e.message}, "
                  f"SIP status: {e.metadata.get('sip_status_code')} "
                  f"{e.metadata.get('sip_status')}")
            ctx.shutdown()

    session = AgentSession(
        stt="deepgram/nova-3:multi",
        llm="openai/gpt-4.1-mini",
        tts="cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )

    # Add this guard to ensure the agent only speaks first in an inbound scenario.
    # When placing an outbound call, its more customary for the recipient to speak first
    # The agent will automatically respond after the user's turn has ended.
    if phone_number is None:
        await session.generate_reply(
            instructions="Greet the user and offer your assistance."
        )


if __name__ == "__main__":
    agents.cli.run_app(server)