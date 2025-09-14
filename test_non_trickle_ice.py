#!/usr/bin/env python3
"""
Test script to verify non-trickle ICE implementation.
"""

import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def test_wait_for_ice_gathering():
    """Test the wait_for_ice_gathering helper function."""
    from agent.core import wait_for_ice_gathering
    from aiortc import RTCPeerConnection, RTCConfiguration

    # Create a mock peer connection
    pc = Mock(spec=RTCPeerConnection)
    pc.iceGatheringState = "gathering"

    # Mock the event system
    listeners = {}

    def mock_on(event, callback):
        listeners[event] = callback

    def mock_remove_listener(event, callback):
        if event in listeners:
            del listeners[event]

    pc.on = mock_on
    pc.remove_listener = mock_remove_listener

    # Test case 1: ICE gathering already complete
    pc.iceGatheringState = "complete"
    await wait_for_ice_gathering(pc, timeout=1.0)
    logger.info("✓ Test 1 passed: ICE gathering already complete")

    # Test case 2: ICE gathering completes during wait
    pc.iceGatheringState = "gathering"
    listeners = {}

    async def test_gathering_complete():
        await asyncio.sleep(0.1)  # Simulate gathering time
        pc.iceGatheringState = "complete"
        if "icegatheringstatechange" in listeners:
            listeners["icegatheringstatechange"]()

    # Start the test
    task = asyncio.create_task(test_gathering_complete())
    await wait_for_ice_gathering(pc, timeout=2.0)
    await task
    logger.info("✓ Test 2 passed: ICE gathering completes during wait")

    # Test case 3: Timeout
    pc.iceGatheringState = "gathering"
    listeners = {}

    start_time = asyncio.get_event_loop().time()
    await wait_for_ice_gathering(pc, timeout=0.5)
    end_time = asyncio.get_event_loop().time()

    # Should timeout after approximately 0.5 seconds
    assert end_time - start_time >= 0.4, f"Timeout too fast: {end_time - start_time}"
    logger.info("✓ Test 3 passed: Timeout works correctly")


async def test_non_trickle_flow():
    """Test the non-trickle ICE flow."""
    from agent.core import AgentCore
    from agent.config import AgentSettings
    from agent.signaling import SignalingClient
    from aiortc import RTCConfiguration

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

        mock_rtc_config.return_value = RTCConfiguration(iceServers=[])
        mock_transport.return_value = Mock()

        agent = AgentCore(settings, signaling)

        # Mock peer connection
        pc = Mock()
        pc.iceGatheringState = "gathering"
        pc.connectionState = "new"
        pc.iceConnectionState = "new"
        pc.createDataChannel = Mock(return_value=Mock())
        pc.createOffer = AsyncMock(return_value=Mock(sdp="test_offer_sdp"))
        pc.createAnswer = AsyncMock(return_value=Mock(sdp="test_answer_sdp"))
        pc.setLocalDescription = AsyncMock()
        pc.setRemoteDescription = AsyncMock()
        pc.addIceCandidate = AsyncMock()
        pc.close = AsyncMock()
        pc.on = Mock()

        # Mock local description
        local_desc = Mock()
        local_desc.sdp = "complete_sdp_with_candidates"
        pc.localDescription = local_desc

        # Test connect_to flow
        with patch("agent.core.RTCPeerConnection", return_value=pc):
            await agent.connect_to("test_peer")

            # Verify that setLocalDescription was called with complete SDP
            pc.setLocalDescription.assert_called_once()

            # Verify that signaling.send was called with complete SDP
            signaling.send.assert_called()
            call_args = signaling.send.call_args[0][0]
            assert call_args["type"] == "offer"
            assert call_args["sdp"] == "complete_sdp_with_candidates"

        logger.info("✓ Test 4 passed: Non-trickle connect_to flow")


async def main():
    """Run all tests."""
    logger.info("Starting non-trickle ICE tests...")

    try:
        await test_wait_for_ice_gathering()
        await test_non_trickle_flow()
        logger.info("🎉 All tests passed!")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
