# mvp-agent/examples/chat_offer.py
"""Example: Chat offerer - initiates connection and sends chat messages."""

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


async def chat_offerer(peer_id: str):
    """
    Chat offerer example - initiates connection and sends messages.

    Args:
        peer_id: ID of the peer to connect to
    """
    logger.info(f"Starting chat offerer to connect to {peer_id}")

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

        # Connect to peer
        logger.info(f"Connecting to peer: {peer_id}")
        await core.connect_to(peer_id)

        # Wait for connection
        logger.info("Waiting for connection...")
        start_time = asyncio.get_event_loop().time()
        timeout = 30.0

        while True:
            session = core.get_session(peer_id)
            if session and session.is_connected():
                logger.info(f"Connected to {peer_id}")
                break

            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.error(f"Connection timeout after {timeout} seconds")
                return 1

            await asyncio.sleep(0.1)

        # Wait for shutdown (handled by transport stdin reader)
        logger.info("Chat session established. Transport will handle stdin/stdout.")
        await core.wait_for_shutdown()

        logger.info("Chat offerer completed")
        return 0

    except Exception as e:
        logger.error(f"Error in chat offerer: {e}")
        return 1
    finally:
        # Cleanup
        if "core" in locals():
            await core.stop()
        logger.info("Chat offerer stopped")


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python chat_offer.py <peer_id>")
        print()
        print("Example:")
        print("  python chat_offer.py peer-123")
        print()
        print("Make sure to set the following environment variables:")
        print("  AGENT_ID=your-agent-id")
        print("  SIGNALING_URL=wss://your-signaling-server.com")
        print("  MODE=chat")
        sys.exit(1)

    peer_id = sys.argv[1]

    try:
        exit_code = asyncio.run(chat_offerer(peer_id))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
