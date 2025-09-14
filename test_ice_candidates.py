#!/usr/bin/env python3
"""
Script để test ICE candidates (non-trickle ICE).
Tạo một WebRTC peer connection, đợi gather hoàn tất,
rồi in ra toàn bộ ICE candidates từ localDescription.sdp.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from aiortc import (
    RTCPeerConnection,
    RTCConfiguration,
    RTCIceServer,
)

# Logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logging.getLogger("aioice").setLevel(logging.DEBUG)
logging.getLogger("aiortc").setLevel(logging.DEBUG)


class NonTrickleICETester:
    def __init__(self):
        self.pc: RTCPeerConnection | None = None

    def load_config_from_env(self) -> Dict[str, Any]:
        """Load ICE server config từ .env"""
        load_dotenv()

        config = {
            "agent_id": os.getenv("AGENT_ID", "ice-tester"),
        }

        ice_servers: list[dict[str, Any]] = []

        ice_urls = os.getenv("ICE_URLS")
        if ice_urls:
            urls = [url.strip() for url in ice_urls.split(",") if url.strip()]
            for url in urls:
                server = {"urls": url}
                if "turn:" in url:
                    if username := os.getenv("ICE_USERNAME"):
                        server["username"] = username
                    if credential := os.getenv("ICE_CREDENTIAL"):
                        server["credential"] = credential
                ice_servers.append(server)

        if not ice_servers:
            ice_servers = [
                {"urls": "stun:stun.l.google.com:19302"},
                {"urls": "stun:stun1.l.google.com:19302"},
            ]
            logger.info("No ICE servers configured, using Google STUN defaults")

        config["ice_servers"] = ice_servers
        return config

    def create_rtc_configuration(self, ice_servers: List[Dict[str, Any]]) -> RTCConfiguration:
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

    async def run(self, config: Dict[str, Any]) -> int:
        """Thực thi test non-trickle ICE"""
        rtc_config = self.create_rtc_configuration(config["ice_servers"])
        self.pc = RTCPeerConnection(rtc_config)

        logger.info("ICE servers configured:")
        for i, server in enumerate(config["ice_servers"], start=1):
            urls = server["urls"]
            if isinstance(urls, str):
                urls = [urls]
            logger.info(f"  {i}. {urls}")
            if server.get("username"):
                logger.info(f"     Username: {server['username']}")

        # Create dummy channel
        self.pc.createDataChannel("test")

        # Create offer
        logger.info("Creating offer...")
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # Wait for ICE gathering complete
        logger.info("Waiting ICE gathering to complete...")
        while self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.5)

        logger.info("ICE gathering completed!")

        # Print summary
        sdp = self.pc.localDescription.sdp
        candidates = [line for line in sdp.splitlines() if line.startswith("a=candidate:")]
        logger.info("\n=== ICE CANDIDATES SUMMARY ===")
        logger.info(f"Total candidates found: {len(candidates)}")
        for i, c in enumerate(candidates, 1):
            logger.info(f"{i}. {c}")

        if not candidates:
            logger.warning("❌ No candidates found!")
            return 1

        logger.info("✅ Test PASSED: Got ICE candidates")
        return 0

    async def cleanup(self):
        if self.pc:
            await self.pc.close()
            logger.info("Peer connection closed")


async def main():
    logger.info("=== Non-Trickle ICE Candidates Test ===")
    tester = NonTrickleICETester()
    try:
        config = tester.load_config_from_env()
        logger.info(f"Loaded configuration for agent: {config['agent_id']}")
        return await tester.run(config)
    except Exception as e:
        logger.exception(f"Test failed with exception: {e}")
        return 1
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
