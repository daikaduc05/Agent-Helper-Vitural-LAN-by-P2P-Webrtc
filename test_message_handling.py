#!/usr/bin/env python3
"""
Test script to verify message handling works correctly.
"""

import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def test_message_handling():
    """Test message handling in AgentCore."""
    from agent.core import AgentCore
    from agent.config import AgentSettings
    from agent.signaling import SignalingClient, MessageType

    # Mock settings
    settings = Mock(spec=AgentSettings)
    settings.agent_id = "test_agent"
    settings.data_channel_label = "test_channel"
    settings.mode = "tun"
    settings.ice_servers = []

    # Mock signaling client
    signaling = Mock(spec=SignalingClient)
    signaling.send = AsyncMock()
    signaling.recv = AsyncMock()
    signaling.connect = AsyncMock()
    signaling.close = AsyncMock()

    # Create agent core
    with patch("agent.core.create_rtc_configuration") as mock_rtc_config, patch(
        "agent.core.create_transport"
    ) as mock_transport:

        mock_rtc_config.return_value = Mock()
        mock_transport.return_value = Mock()

        agent = AgentCore(settings, signaling)

        # Test message handling
        test_messages = [
            {
                "type": MessageType.OFFER,
                "from": "peer1",
                "to": "test_agent",
                "sdp": "test_offer_sdp",
            },
            {
                "type": MessageType.ANSWER,
                "from": "peer1",
                "to": "test_agent",
                "sdp": "test_answer_sdp",
            },
            {
                "type": MessageType.CANDIDATE,
                "from": "peer1",
                "to": "test_agent",
                "candidate": "test_candidate",
            },
        ]

        for msg in test_messages:
            logger.info(f"Testing message: {msg['type']}")
            try:
                await agent._handle_incoming(msg)
                logger.info(f"✓ Successfully handled {msg['type']} message")
            except Exception as e:
                logger.error(f"❌ Failed to handle {msg['type']} message: {e}")
                import traceback

                logger.error(f"Traceback: {traceback.format_exc()}")


async def main():
    """Run message handling test."""
    logger.info("Starting message handling test...")

    try:
        await test_message_handling()
        logger.info("🎉 Message handling test completed!")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
