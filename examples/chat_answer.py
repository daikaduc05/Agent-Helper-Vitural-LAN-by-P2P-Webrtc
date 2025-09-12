# mvp-agent/examples/chat_answer.py
"""Example: Chat answerer - listens for connections and responds to chat messages."""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import AgentCore, AgentSettings, SignalingClient, load_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def chat_answerer():
    """
    Chat answerer example - listens for connections and responds to messages.
    """
    logger.info("Starting chat answerer")

    try:
        # Load settings
        settings = load_settings()
        logger.info(f"Loaded settings for agent: {settings.agent_id}")

        # Create signaling client and core
        signaling = SignalingClient(settings)
        core = AgentCore(settings, signaling)

        # Start core
        await core.start()
        logger.info("Agent core started")

        # Listen for connections
        logger.info(f"Listening for connections (agent: {settings.agent_id})")
        logger.info("Waiting for incoming offers...")

        # Wait for a connection
        start_time = asyncio.get_event_loop().time()
        timeout = 60.0  # Wait up to 60 seconds for a connection

        while True:
            sessions = core.get_all_sessions()
            if sessions:
                # Get the first connected session
                for peer_id, session in sessions.items():
                    if session.is_connected():
                        logger.info(f"Connected to {peer_id}")
                        await handle_chat_session(core, peer_id)
                        return 0

                # Check if any session is connecting
                for peer_id, session in sessions.items():
                    if session.pc.connectionState in ["connecting", "connected"]:
                        logger.info(f"Connection in progress with {peer_id}")
                        # Wait a bit more for connection to complete
                        await asyncio.sleep(1.0)
                        continue

            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.warning(f"No connection received within {timeout} seconds")
                return 1

            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Error in chat answerer: {e}")
        return 1
    finally:
        # Cleanup
        if "core" in locals():
            await core.stop()
        logger.info("Chat answerer stopped")


async def handle_chat_session(core: AgentCore, peer_id: str):
    """
    Handle chat session with a connected peer.

    Args:
        core: Agent core instance
        peer_id: ID of the connected peer
    """
    logger.info(f"Handling chat session with {peer_id}")

    session = core.get_session(peer_id)
    if not session:
        logger.error(f"No session found for {peer_id}")
        return

    transport = session.transport
    message_count = 0

    def on_message(data: bytes):
        nonlocal message_count
        try:
            text = data.decode("utf-8")
            print(f"< {text}")
            message_count += 1

            # Send a response
            response = f"Response {message_count}: Received '{text}'"
            print(f"> {response}")
            transport.send_text(response)

        except UnicodeDecodeError:
            print(f"< [binary data: {len(data)} bytes]")

    transport.on_message(on_message)

    print(f"Chat session with {peer_id} established.")
    print("Listening for messages and sending responses...")
    print("Press Ctrl+C to exit.")

    # Wait for messages
    try:
        while True:
            await asyncio.sleep(1.0)

            # Check if connection is still alive
            if not session.is_connected():
                logger.info(f"Connection to {peer_id} lost")
                break

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error in chat session: {e}")


def main():
    """Main entry point."""
    print("Chat Answerer Example")
    print("====================")
    print()
    print(
        "This example listens for incoming WebRTC connections and responds to chat messages."
    )
    print()
    print("Make sure to set the following environment variables:")
    print("  AGENT_ID=your-agent-id")
    print("  SIGNALING_URL=wss://your-signaling-server.com")
    print("  MODE=chat")
    print()
    print("Then run the chat offerer example to connect to this answerer.")
    print()

    try:
        exit_code = asyncio.run(chat_answerer())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
