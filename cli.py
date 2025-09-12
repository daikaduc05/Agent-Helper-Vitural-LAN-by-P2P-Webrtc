# mvp-agent/cli.py
"""Command-line interface for MVP Agent."""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

import click

from agent import AgentCore, AgentSettings, SignalingClient, load_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class CLIContext:
    """CLI context for sharing state between commands."""

    def __init__(self):
        self.settings: Optional[AgentSettings] = None
        self.signaling: Optional[SignalingClient] = None
        self.core: Optional[AgentCore] = None
        self.shutdown_event = asyncio.Event()


@click.group()
@click.option("--config", "-c", help="Path to config file (YAML/JSON)")
@click.option("--env", "-e", help="Path to .env file")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx, config, env, verbose):
    """MVP Agent - WebRTC Data Channel Agent CLI."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load settings
    try:
        settings = load_settings(config_file=config, env_file=env)
        ctx.obj = CLIContext()
        ctx.obj.settings = settings
        logger.info(f"Loaded settings for agent: {settings.agent_id}")
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        sys.exit(1)


@cli.command()
@click.argument("peer_id")
@click.option("--timeout", "-t", default=30, help="Connection timeout in seconds")
@click.pass_context
def connect(ctx, peer_id: str, timeout: int):
    """Connect to a peer and start interactive session."""

    async def _connect():
        context = ctx.obj
        settings = context.settings

        try:
            # Create signaling client and core
            signaling = SignalingClient(settings)
            core = AgentCore(settings, signaling)
            context.signaling = signaling
            context.core = core

            # Set up signal handlers
            def signal_handler():
                logger.info("Received shutdown signal")
                context.shutdown_event.set()

            loop = asyncio.get_event_loop()
            try:
                loop.add_signal_handler(signal.SIGINT, signal_handler)
                loop.add_signal_handler(signal.SIGTERM, signal_handler)
            except NotImplementedError:
                # Windows doesn't support signal handlers
                logger.debug("Signal handlers not supported on this platform")

            # Start core
            await core.start()

            # Connect to peer
            logger.info(f"Connecting to peer: {peer_id}")
            await core.connect_to(peer_id)

            # Wait for connection with timeout
            start_time = asyncio.get_event_loop().time()
            while not context.shutdown_event.is_set():
                session = core.get_session(peer_id)
                if session and session.is_connected():
                    logger.info(f"Connected to {peer_id}")
                    break

                if asyncio.get_event_loop().time() - start_time > timeout:
                    logger.error(f"Connection timeout after {timeout} seconds")
                    return 1

                await asyncio.sleep(0.1)

            if context.shutdown_event.is_set():
                return 0

            # Start interactive session based on mode
            if settings.mode == "chat":
                await _interactive_chat(core, peer_id, context.shutdown_event)
            elif settings.mode == "json":
                await _interactive_json(core, peer_id, context.shutdown_event)
            elif settings.mode == "bytes":
                await _interactive_bytes(core, peer_id, context.shutdown_event)
            elif settings.mode == "tun":
                await _interactive_tun(core, peer_id, context.shutdown_event)
            else:
                logger.error(f"Unsupported mode: {settings.mode}")
                return 1

        except Exception as e:
            import traceback

            logger.error(f"Error in connect: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return 1
        finally:
            # Cleanup
            if context.core:
                await context.core.stop()
            logger.info("Connection closed")

        return 0

    try:
        exit_code = asyncio.run(_connect())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


@cli.command()
@click.option("--timeout", "-t", default=30, help="Connection timeout in seconds")
@click.pass_context
def listen(ctx, timeout: int):
    """Listen for incoming connections and auto-answer."""

    async def _listen():
        context = ctx.obj
        settings = context.settings

        try:
            # Create signaling client and core
            signaling = SignalingClient(settings)
            core = AgentCore(settings, signaling)
            context.signaling = signaling
            context.core = core

            # Set up signal handlers
            def signal_handler():
                logger.info("Received shutdown signal")
                context.shutdown_event.set()

            loop = asyncio.get_event_loop()
            try:
                loop.add_signal_handler(signal.SIGINT, signal_handler)
                loop.add_signal_handler(signal.SIGTERM, signal_handler)
            except NotImplementedError:
                # Windows doesn't support signal handlers
                logger.debug("Signal handlers not supported on this platform")

            # Start core
            await core.start()

            logger.info(f"Listening for connections (agent: {settings.agent_id})")
            logger.info("Press Ctrl+C to stop")

            # Wait for shutdown
            await context.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Error in listen: {e}")
            return 1
        finally:
            # Cleanup
            if context.core:
                await context.core.stop()
            logger.info("Listener stopped")

        return 0

    try:
        exit_code = asyncio.run(_listen())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


@cli.command()
@click.pass_context
def status(ctx):
    """Show current connection status."""

    async def _status():
        context = ctx.obj
        settings = context.settings

        try:
            # Create signaling client and core
            signaling = SignalingClient(settings)
            core = AgentCore(settings, signaling)
            context.signaling = signaling
            context.core = core
            # Start core
            await core.start()

            # Get status
            stats = core.get_stats()

            print(f"Agent ID: {stats['agent_id']}")
            print(f"Peer Count: {stats['peer_count']}")
            print()

            if stats["peers"]:
                print("Connected Peers:")
                for peer_id, peer_stats in stats["peers"].items():
                    print(f"  {peer_id}:")
                    print(f"    Connection State: {peer_stats['connection_state']}")
                    print(f"    ICE State: {peer_stats['ice_connection_state']}")
                    print(f"    Data Channel: {peer_stats['data_channel_state']}")
                    print(f"    Uptime: {peer_stats['uptime']:.1f}s")
                    print()
            else:
                print("No connected peers")

        except Exception as e:
            logger.error(f"Error in status: {e}")
            return 1
        finally:
            # Cleanup
            if context.core:
                await context.core.stop()

        return 0

    try:
        exit_code = asyncio.run(_status())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


async def _interactive_chat(
    core: AgentCore, peer_id: str, shutdown_event: asyncio.Event
):
    """Interactive chat session."""
    session = core.get_session(peer_id)
    if not session:
        logger.error(f"No session found for {peer_id}")
        return

    transport = session.transport

    # Set up message handler
    def on_message(data: bytes):
        try:
            text = data.decode("utf-8")
            print(f"< {text}")
        except UnicodeDecodeError:
            print(f"< [binary data: {len(data)} bytes]")

    transport.on_message(on_message)

    print(f"Chat session with {peer_id} started. Type messages and press Enter.")
    print("Type 'quit' to exit.")

    # Start stdin reader
    async def stdin_reader():
        loop = asyncio.get_event_loop()
        while not shutdown_event.is_set():
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line or line.strip() == "quit":
                    shutdown_event.set()
                    break

                text = line.strip()
                if text:
                    transport.send_text(text)
                    print(f"> {text}")
            except Exception as e:
                logger.error(f"Error reading stdin: {e}")
                break

    # Run stdin reader
    await stdin_reader()


async def _interactive_json(
    core: AgentCore, peer_id: str, shutdown_event: asyncio.Event
):
    """Interactive JSON session."""
    session = core.get_session(peer_id)
    if not session:
        logger.error(f"No session found for {peer_id}")
        return

    transport = session.transport

    # Set up message handler
    def on_message(data: bytes):
        try:
            import json

            text = data.decode("utf-8")
            obj = json.loads(text)
            print(f"< {json.dumps(obj, indent=2)}")
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            print(f"< [invalid JSON: {e}]")

    transport.on_message(on_message)

    print(f"JSON session with {peer_id} started. Type JSON objects and press Enter.")
    print("Type 'quit' to exit.")

    # Start stdin reader
    async def stdin_reader():
        loop = asyncio.get_event_loop()
        while not shutdown_event.is_set():
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line or line.strip() == "quit":
                    shutdown_event.set()
                    break

                text = line.strip()
                if text:
                    try:
                        import json

                        obj = json.loads(text)
                        transport.send_json(obj)
                        print(f"> {json.dumps(obj, indent=2)}")
                    except json.JSONDecodeError as e:
                        print(f"Error: Invalid JSON - {e}")
            except Exception as e:
                logger.error(f"Error reading stdin: {e}")
                break

    # Run stdin reader
    await stdin_reader()


async def _interactive_bytes(
    core: AgentCore, peer_id: str, shutdown_event: asyncio.Event
):
    """Interactive bytes session."""
    session = core.get_session(peer_id)
    if not session:
        logger.error(f"No session found for {peer_id}")
        return

    transport = session.transport

    # Set up message handler
    def on_message(data: bytes):
        print(f"< [received {len(data)} bytes]")
        # Show hex dump for small data
        if len(data) <= 64:
            hex_str = " ".join(f"{b:02x}" for b in data)
            print(f"< hex: {hex_str}")

    transport.on_message(on_message)

    print(f"Bytes session with {peer_id} started. Type hex data and press Enter.")
    print("Type 'quit' to exit.")

    # Start stdin reader
    async def stdin_reader():
        loop = asyncio.get_event_loop()
        while not shutdown_event.is_set():
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line or line.strip() == "quit":
                    shutdown_event.set()
                    break

                text = line.strip()
                if text:
                    try:
                        # Parse hex string
                        hex_data = text.replace(" ", "").replace("\n", "")
                        if len(hex_data) % 2 != 0:
                            print("Error: Hex string must have even length")
                            continue

                        data = bytes.fromhex(hex_data)
                        transport.send_bytes(data)
                        print(f"> [sent {len(data)} bytes]")
                    except ValueError as e:
                        print(f"Error: Invalid hex - {e}")
            except Exception as e:
                logger.error(f"Error reading stdin: {e}")
                break

    # Run stdin reader
    await stdin_reader()


async def _interactive_tun(
    core: AgentCore, peer_id: str, shutdown_event: asyncio.Event
):
    """Interactive TUN session."""
    session = core.get_session(peer_id)
    if not session:
        logger.error(f"No session found for {peer_id}")
        return

    transport = session.transport

    # Set up message handler
    def on_message(data: bytes):
        print(f"< [received packet: {len(data)} bytes]")

    transport.on_message(on_message)

    print(f"TUN session with {peer_id} started.")
    print("Packets will be exchanged automatically.")
    print("Press Ctrl+C to exit.")

    # Wait for shutdown
    await shutdown_event.wait()


if __name__ == "__main__":
    cli()
