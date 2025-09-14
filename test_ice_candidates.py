#!/usr/bin/env python3
"""
Script để test việc gather ICE candidates.
Tạo một WebRTC peer connection và log tất cả ICE candidates nhận được.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add agent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from aiortc import (
    RTCPeerConnection,
    RTCConfiguration,
    RTCIceServer,
    RTCIceCandidate,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logging.getLogger("aioice").setLevel(logging.DEBUG)
logging.getLogger("aiortc").setLevel(logging.DEBUG)


class ICECandidateTester:
    """Class để test ICE candidates."""

    def __init__(self):
        self.pc: RTCPeerConnection | None = None
        self.candidates_received: List[RTCIceCandidate] = []
        self.ice_gathering_complete = False
        self.gathering_started = False

    def load_config_from_env(self) -> Dict[str, Any]:
        """Load cấu hình từ biến môi trường."""
        load_dotenv()

        config = {
            "agent_id": os.getenv("AGENT_ID", "ice-tester"),
        }

        # Load ICE servers configuration
        ice_servers: list[dict[str, Any]] = []

        # Single ICE server
        ice_url = os.getenv("ICE_URL")
        if ice_url:
            server = self._parse_ice_server(ice_url)
            if server:
                ice_servers.append(server)

        # Multiple ICE servers
        ice_urls = os.getenv("ICE_URLS")
        if ice_urls:
            urls = [url.strip() for url in ice_urls.split(",") if url.strip()]
            for url in urls:
                server = self._parse_ice_server(url)
                if server:
                    ice_servers.append(server)

        # Default Google STUN nếu không có gì
        if not ice_servers:
            ice_servers = [
                {"urls": "stun:stun.l.google.com:19302"},
                {"urls": "stun:stun1.l.google.com:19302"},
            ]
            logger.info("No ICE servers configured, using default Google STUN")

        config["ice_servers"] = ice_servers
        return config

    def _parse_ice_server(self, url: str) -> Dict[str, Any]:
        """Parse ICE server URL và thêm transport parameter nếu cần."""
        server = {"urls": url}

        # Thêm transport parameter cho TURN servers
        if "turn:" in url and "transport=" not in url:
            # Thêm cả UDP và TCP
            server["urls"] = [f"{url}?transport=udp", f"{url}?transport=tcp"]

        # Thêm credentials cho TURN
        if "turn:" in url:
            if username := os.getenv("ICE_USERNAME"):
                server["username"] = username
            if credential := os.getenv("ICE_CREDENTIAL"):
                server["credential"] = credential

        return server

    def create_rtc_configuration(
        self, ice_servers: List[Dict[str, Any]]
    ) -> RTCConfiguration:
        """Tạo RTCConfiguration từ danh sách ICE servers."""
        rtc_ice_servers = []
        for server in ice_servers:
            urls = server["urls"]
            if isinstance(urls, str):
                urls = [urls]

            rtc_server = RTCIceServer(
                urls=urls,
                username=server.get("username"),
                credential=server.get("credential"),
            )
            rtc_ice_servers.append(rtc_server)

        return RTCConfiguration(iceServers=rtc_ice_servers)

    async def setup_peer_connection(self, config: Dict[str, Any]):
        """Thiết lập peer connection với ICE candidate handlers."""
        rtc_config = self.create_rtc_configuration(config["ice_servers"])
        self.pc = RTCPeerConnection(rtc_config)

        # Log ICE servers
        logger.info("ICE servers configured:")
        for i, server in enumerate(config["ice_servers"], start=1):
            urls = server["urls"]
            if isinstance(urls, str):
                urls = [urls]
            logger.info(f"  {i}. {urls}")
            if server.get("username"):
                logger.info(f"     Username: {server['username']}")

        # Callbacks
        @self.pc.on("icecandidate")
        def on_icecandidate(candidate: RTCIceCandidate | None):
            if candidate:
                self.candidates_received.append(candidate)
                logger.info(
                    f"[ICE_CANDIDATE] Type: {candidate.type}, Protocol: {candidate.protocol}, Address: {candidate.address}:{candidate.port}"
                )
                logger.info(f"[ICE_CANDIDATE_FULL] {candidate.to_sdp()}")
            else:
                logger.info("[END_OF_CANDIDATES]")
                self.ice_gathering_complete = True

        @self.pc.on("icegatheringstatechange")
        def on_ice_gathering_state_change():
            state = self.pc.iceGatheringState
            logger.info(f"ICE gathering state: {state}")
            if state == "gathering":
                self.gathering_started = True

        @self.pc.on("iceconnectionstatechange")
        def on_ice_connection_state_change():
            logger.info(f"ICE connection state: {self.pc.iceConnectionState}")

        @self.pc.on("connectionstatechange")
        def on_connection_state_change():
            logger.info(f"Connection state: {self.pc.connectionState}")

    async def test_ice_gathering(self) -> int:
        """Test ICE candidate gathering."""
        logger.info("Starting ICE candidate gathering test...")

        # Create dummy data channel
        self.pc.createDataChannel("test-channel")

        # Create and set local offer
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # Chờ gathering bắt đầu
        gathering_timeout = 5.0
        start_time = asyncio.get_event_loop().time()
        while not self.gathering_started:
            if asyncio.get_event_loop().time() - start_time > gathering_timeout:
                logger.error("ICE gathering never started!")
                return 0
            await asyncio.sleep(0.1)

        logger.info("ICE gathering started, waiting for candidates...")

        # Wait for gathering to complete
        timeout = 30.0
        start_time = asyncio.get_event_loop().time()

        while not self.ice_gathering_complete:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.warning(f"ICE gathering timeout after {timeout} seconds")
                break
            await asyncio.sleep(0.5)

        # Summary
        logger.info("\n=== ICE CANDIDATES SUMMARY ===")
        logger.info(f"Total candidates received: {len(self.candidates_received)}")

        if self.candidates_received:
            candidate_types: dict[str, int] = {}
            protocols: dict[str, int] = {}

            for c in self.candidates_received:
                candidate_types[c.type] = candidate_types.get(c.type, 0) + 1
                protocols[c.protocol] = protocols.get(c.protocol, 0) + 1

            logger.info("Candidates by type:")
            for t, count in candidate_types.items():
                logger.info(f"  {t}: {count}")

            logger.info("Candidates by protocol:")
            for p, count in protocols.items():
                logger.info(f"  {p}: {count}")

            logger.info("Detailed candidate list:")
            for i, c in enumerate(self.candidates_received, 1):
                logger.info(f"  {i}. {c.type} ({c.protocol}) {c.address}:{c.port}")
        else:
            logger.warning("No ICE candidates received!")

        return len(self.candidates_received)

    async def cleanup(self):
        if self.pc:
            await self.pc.close()
            logger.info("Peer connection closed")


async def main():
    logger.info("=== ICE Candidates Test Script ===")

    tester = ICECandidateTester()
    try:
        config = tester.load_config_from_env()
        logger.info(f"Loaded configuration for agent: {config['agent_id']}")

        await tester.setup_peer_connection(config)
        count = await tester.test_ice_gathering()

        if count > 0:
            logger.info(f"✅ Test PASSED: Received {count} ICE candidates")
            return 0
        else:
            logger.error("❌ Test FAILED: No ICE candidates received")
            return 1

    except Exception as e:
        logger.exception(f"❌ Test ERROR: {e}")
        return 1
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        sys.exit(0)
