# mvp-agent/examples/lan_demo.py
"""Example: LAN demo with TUN interface for VPN-like functionality."""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import AgentCore, AgentSettings, SignalingClient, load_settings
from agent.tun import create_tun, TunDevice, check_tun_support

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def lan_demo_offerer(peer_id: str):
    """
    LAN demo offerer - creates TUN interface and connects to peer.

    Args:
        peer_id: ID of the peer to connect to
    """
    logger.info(f"Starting LAN demo offerer to connect to {peer_id}")

    # Check TUN support
    if not check_tun_support():
        logger.error("TUN/TAP support not available on this system")
        logger.error("This demo requires Linux with /dev/net/tun")
        return 1

    try:
        # Load settings
        settings = load_settings()
        if settings.mode != "tun":
            logger.warning(
                f"Settings mode is '{settings.mode}', but this demo requires 'tun'"
            )
            logger.info("Setting mode to 'tun' for this demo")
            settings.mode = "tun"

        logger.info(f"Loaded settings for agent: {settings.agent_id}")

        # Create TUN interface
        logger.info("Creating TUN interface...")
        tun_fd, tun_name = create_tun("mvp-tun0")
        tun_device = TunDevice(tun_fd, tun_name)

        logger.info(f"Created TUN interface: {tun_name}")
        logger.info("You may need to configure the interface:")
        logger.info(f"  sudo ip addr add 10.0.0.1/24 dev {tun_name}")
        logger.info(f"  sudo ip link set {tun_name} up")

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

        # Set up TUN integration
        transport = session.transport
        transport._tun_device = tun_device

        # Set up packet handlers
        def on_packet(data: bytes):
            logger.debug(f"Received packet from peer: {len(data)} bytes")
            # Write to TUN interface
            asyncio.create_task(tun_device.write_packet(data))

        transport.on_message(on_packet)

        # Start TUN read loop
        logger.info("Starting TUN read loop...")
        tun_task = asyncio.create_task(
            tun_device.read_loop(lambda packet: transport.send_bytes(packet))
        )

        print(f"LAN demo with {peer_id} established.")
        print(f"TUN interface: {tun_name}")
        print("Packets will be exchanged between TUN interface and peer.")
        print("Press Ctrl+C to exit.")

        try:
            # Wait for TUN task or user interrupt
            await tun_task
        except asyncio.CancelledError:
            logger.info("TUN read loop cancelled")

        logger.info("LAN demo offerer completed")
        return 0

    except Exception as e:
        logger.error(f"Error in LAN demo offerer: {e}")
        return 1
    finally:
        # Cleanup
        if "tun_device" in locals():
            tun_device.close()
        if "core" in locals():
            await core.stop()
        logger.info("LAN demo offerer stopped")


async def lan_demo_answerer():
    """
    LAN demo answerer - listens for connections and sets up TUN interface.
    """
    logger.info("Starting LAN demo answerer")

    # Check TUN support
    if not check_tun_support():
        logger.error("TUN/TAP support not available on this system")
        logger.error("This demo requires Linux with /dev/net/tun")
        return 1

    try:
        # Load settings
        settings = load_settings()
        if settings.mode != "tun":
            logger.warning(
                f"Settings mode is '{settings.mode}', but this demo requires 'tun'"
            )
            logger.info("Setting mode to 'tun' for this demo")
            settings.mode = "tun"

        logger.info(f"Loaded settings for agent: {settings.agent_id}")

        # Create TUN interface
        logger.info("Creating TUN interface...")
        tun_fd, tun_name = create_tun("mvp-tun1")
        tun_device = TunDevice(tun_fd, tun_name)

        logger.info(f"Created TUN interface: {tun_name}")
        logger.info("You may need to configure the interface:")
        logger.info(f"  sudo ip addr add 10.0.0.2/24 dev {tun_name}")
        logger.info(f"  sudo ip link set {tun_name} up")

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
                        await handle_lan_session(core, peer_id, tun_device)
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
        logger.error(f"Error in LAN demo answerer: {e}")
        return 1
    finally:
        # Cleanup
        if "tun_device" in locals():
            tun_device.close()
        if "core" in locals():
            await core.stop()
        logger.info("LAN demo answerer stopped")


async def handle_lan_session(core: AgentCore, peer_id: str, tun_device: TunDevice):
    """
    Handle LAN session with a connected peer.

    Args:
        core: Agent core instance
        peer_id: ID of the connected peer
        tun_device: TUN device instance
    """
    logger.info(f"Handling LAN session with {peer_id}")

    session = core.get_session(peer_id)
    if not session:
        logger.error(f"No session found for {peer_id}")
        return

    transport = session.transport
    transport._tun_device = tun_device

    # Set up packet handlers
    def on_packet(data: bytes):
        logger.debug(f"Received packet from peer: {len(data)} bytes")
        # Write to TUN interface
        asyncio.create_task(tun_device.write_packet(data))

    transport.on_message(on_packet)

    # Start TUN read loop
    logger.info("Starting TUN read loop...")
    tun_task = asyncio.create_task(
        tun_device.read_loop(lambda packet: transport.send_bytes(packet))
    )

    print(f"LAN demo with {peer_id} established.")
    print(f"TUN interface: {tun_device.name}")
    print("Packets will be exchanged between TUN interface and peer.")
    print("Press Ctrl+C to exit.")

    try:
        # Wait for TUN task or user interrupt
        await tun_task
    except asyncio.CancelledError:
        logger.info("TUN read loop cancelled")
    except Exception as e:
        logger.error(f"Error in LAN session: {e}")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python lan_demo.py offer <peer_id>    # Start as offerer")
        print("  python lan_demo.py answer             # Start as answerer")
        print()
        print("Example:")
        print("  python lan_demo.py offer peer-123")
        print("  python lan_demo.py answer")
        print()
        print("Requirements:")
        print("  - Linux system with /dev/net/tun")
        print("  - Root privileges or CAP_NET_ADMIN capability")
        print("  - Environment variables:")
        print("    AGENT_ID=your-agent-id")
        print("    SIGNALING_URL=wss://your-signaling-server.com")
        print("    MODE=tun")
        print()
        print("After starting, configure the TUN interfaces:")
        print("  # On offerer (10.0.0.1):")
        print("  sudo ip addr add 10.0.0.1/24 dev mvp-tun0")
        print("  sudo ip link set mvp-tun0 up")
        print()
        print("  # On answerer (10.0.0.2):")
        print("  sudo ip addr add 10.0.0.2/24 dev mvp-tun1")
        print("  sudo ip link set mvp-tun1 up")
        print()
        print("Then test connectivity:")
        print("  ping 10.0.0.2  # From offerer")
        print("  ping 10.0.0.1  # From answerer")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "offer":
        if len(sys.argv) != 3:
            print("Error: peer_id required for offer mode")
            sys.exit(1)
        peer_id = sys.argv[2]

        try:
            exit_code = asyncio.run(lan_demo_offerer(peer_id))
            sys.exit(exit_code)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            sys.exit(0)

    elif mode == "answer":
        try:
            exit_code = asyncio.run(lan_demo_answerer())
            sys.exit(exit_code)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            sys.exit(0)

    else:
        print(f"Error: Unknown mode '{mode}'")
        print("Use 'offer' or 'answer'")
        sys.exit(1)


if __name__ == "__main__":
    main()
