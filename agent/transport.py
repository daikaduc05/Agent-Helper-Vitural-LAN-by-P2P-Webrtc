# mvp-agent/agent/transport.py
"""Data transport abstraction layer for WebRTC data channels."""

import asyncio
import json
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Union

from aiortc import RTCDataChannel

logger = logging.getLogger(__name__)


class TransportError(Exception):
    """Transport-specific exception."""

    pass


class Transport(ABC):
    """Abstract base class for data transport implementations."""

    def __init__(self, max_queue_size: int = 1000):
        """
        Initialize transport.

        Args:
            max_queue_size: Maximum size of outbound message queue
        """
        self._channel: Optional[RTCDataChannel] = None
        self._message_callback: Optional[Callable[[bytes], None]] = None
        self._outbox_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_queue_size)
        self._sender_task: Optional[asyncio.Task] = None
        self._stdin_reader_task: Optional[asyncio.Task] = None
        self._max_queue_size = max_queue_size
        self._shutdown_event = asyncio.Event()

        logger.debug(f"Transport initialized with max queue size: {max_queue_size}")

    def attach_channel(self, channel: RTCDataChannel) -> None:
        """
        Attach WebRTC data channel to transport.

        Args:
            channel: RTCDataChannel instance
        """
        if self._channel is not None:
            logger.warning("Channel already attached, replacing")

        self._channel = channel
        self._channel.on("message", self._on_channel_message)
        self._channel.on("open", self._on_channel_open)
        self._channel.on("close", self._on_channel_close)

        logger.info(f"Attached channel: {channel.label}")

    def on_message(self, callback: Callable[[bytes], None]) -> None:
        """
        Register callback for incoming messages.

        Args:
            callback: Function to call with raw bytes
        """
        self._message_callback = callback
        logger.debug("Message callback registered")

    def set_default_message_handler(self) -> None:
        """Set up default message handler that logs received messages and prints to console."""

        def handle_message(data: bytes):
            try:
                text = data.decode("utf-8", errors="ignore")
                print(f"> {text}")  # Print to console
                logger.info(f"[MESSAGE_RECEIVED] {text}")
            except Exception as e:
                logger.error(f"Failed to decode message: {e}")

        self.on_message(handle_message)
        logger.debug("Default message handler registered")

    def _on_channel_message(self, message: Union[str, bytes]) -> None:
        """Handle incoming channel message."""
        try:
            if isinstance(message, str):
                data = message.encode("utf-8")
            else:
                data = message

            if self._message_callback:
                self._message_callback(data)
            else:
                logger.debug("Message received but no callback registered")
        except Exception as e:
            logger.error(f"Error handling channel message: {e}")

    def _on_channel_open(self) -> None:
        """Handle channel open event."""
        logger.info("Data channel opened")
        print("Chat session started. Type 'quit' to exit.")
        self._start_sender()
        self._start_stdin_reader()

    def _on_channel_close(self) -> None:
        """Handle channel close event."""
        logger.info("Data channel closed")
        self._stop_sender()
        self._stop_stdin_reader()

    def _start_sender(self) -> None:
        """Start background task to send queued messages."""
        if self._sender_task is None or self._sender_task.done():
            self._sender_task = asyncio.create_task(self._sender_loop())
            logger.debug("Started message sender task")

    def _stop_sender(self) -> None:
        """Stop background sender task."""
        if self._sender_task and not self._sender_task.done():
            self._sender_task.cancel()
            logger.debug("Stopped message sender task")

    def _start_stdin_reader(self) -> None:
        """Start background task to read from stdin."""
        if self._stdin_reader_task is None or self._stdin_reader_task.done():
            self._stdin_reader_task = asyncio.create_task(self._stdin_reader_loop())
            logger.debug("Started stdin reader task")

    def _stop_stdin_reader(self) -> None:
        """Stop background stdin reader task."""
        if self._stdin_reader_task and not self._stdin_reader_task.done():
            self._stdin_reader_task.cancel()
            logger.debug("Stopped stdin reader task")

    async def _sender_loop(self) -> None:
        """Background task to send queued messages."""
        try:
            while (
                self._channel
                and self._channel.readyState == "open"
                and not self._shutdown_event.is_set()
            ):
                try:
                    message = await asyncio.wait_for(
                        self._outbox_queue.get(), timeout=1.0
                    )
                    await self._send_raw(message)
                    self._outbox_queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in sender loop: {e}")
        except asyncio.CancelledError:
            logger.debug("Sender loop cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in sender loop: {e}")

    async def _stdin_reader_loop(self) -> None:
        """Background task to read from stdin and send messages."""
        try:
            loop = asyncio.get_event_loop()
            while not self._shutdown_event.is_set():
                try:
                    # Read from stdin in executor to avoid blocking
                    line = await loop.run_in_executor(None, sys.stdin.readline)
                    if not line:
                        continue

                    text = line.strip()
                    if text.lower() == "quit":
                        logger.info("User requested quit")
                        self._shutdown_event.set()
                        break

                    if text:  # Only send non-empty messages
                        self.send_text(text)
                        print(f"me: {text}")
                        logger.info(f"[MESSAGE_SENT] {text}")

                except Exception as e:
                    logger.error(f"Error reading from stdin: {e}")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug("Stdin reader loop cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in stdin reader loop: {e}")

    async def _send_raw(self, data: bytes) -> None:
        """Send raw bytes over data channel."""
        if not self._channel or self._channel.readyState != "open":
            raise TransportError("Data channel not available or not open")

        try:
            self._channel.send(data)
        except Exception as e:
            logger.error(f"Failed to send data: {e}")
            raise TransportError(f"Failed to send data: {e}")

    def _queue_message(self, data: bytes) -> None:
        """Queue message for sending."""
        try:
            self._outbox_queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning(
                f"Outbox queue full ({self._max_queue_size}), dropping message"
            )
            # Try to remove oldest message and add new one
            try:
                self._outbox_queue.get_nowait()
                self._outbox_queue.put_nowait(data)
                logger.warning("Dropped oldest message to make room")
            except asyncio.QueueEmpty:
                pass

    @abstractmethod
    def send_text(self, text: str) -> None:
        """Send text message."""
        pass

    @abstractmethod
    def send_json(self, obj: Dict[str, Any]) -> None:
        """Send JSON object."""
        pass

    @abstractmethod
    def send_bytes(self, data: bytes) -> None:
        """Send raw bytes."""
        pass

    async def close(self) -> None:
        """Close transport and cleanup resources."""
        logger.info("Closing transport")

        self._shutdown_event.set()
        self._stop_sender()
        self._stop_stdin_reader()

        # Wait for tasks to complete
        tasks = []
        if self._sender_task and not self._sender_task.done():
            tasks.append(self._sender_task)
        if self._stdin_reader_task and not self._stdin_reader_task.done():
            tasks.append(self._stdin_reader_task)

        if tasks:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        self._channel = None
        self._message_callback = None

        logger.info("Transport closed")


class ChatTransport(Transport):
    """Transport for UTF-8 text messages."""

    def send_text(self, text: str) -> None:
        """Send UTF-8 text message."""
        try:
            data = text.encode("utf-8")
            self._queue_message(data)
            # Note: [MESSAGE_SENT] logging is handled in _stdin_reader_loop
        except UnicodeEncodeError as e:
            logger.error(f"Failed to encode text: {e}")
            raise TransportError(f"Failed to encode text: {e}")

    def send_json(self, obj: Dict[str, Any]) -> None:
        """Send JSON object as text."""
        try:
            json_str = json.dumps(obj, ensure_ascii=False)
            self.send_text(json_str)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize JSON: {e}")
            raise TransportError(f"Failed to serialize JSON: {e}")

    def send_bytes(self, data: bytes) -> None:
        """Send raw bytes (will be treated as UTF-8)."""
        try:
            # Validate that bytes can be decoded as UTF-8
            data.decode("utf-8")
            self._queue_message(data)
            logger.debug(f"Queued bytes message: {len(data)} bytes")
        except UnicodeDecodeError as e:
            logger.error(f"Bytes cannot be decoded as UTF-8: {e}")
            raise TransportError(f"Bytes cannot be decoded as UTF-8: {e}")


class JsonTransport(Transport):
    """Transport for JSON messages."""

    def send_text(self, text: str) -> None:
        """Send text as JSON string."""
        try:
            # Try to parse as JSON first
            json.loads(text)
            data = text.encode("utf-8")
            self._queue_message(data)
            logger.debug(f"Queued JSON text: {len(data)} bytes")
        except json.JSONDecodeError as e:
            logger.error(f"Text is not valid JSON: {e}")
            raise TransportError(f"Text is not valid JSON: {e}")

    def send_json(self, obj: Dict[str, Any]) -> None:
        """Send JSON object."""
        try:
            json_str = json.dumps(obj, ensure_ascii=False)
            data = json_str.encode("utf-8")
            self._queue_message(data)
            logger.debug(f"Queued JSON object: {len(data)} bytes")
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize JSON: {e}")
            raise TransportError(f"Failed to serialize JSON: {e}")

    def send_bytes(self, data: bytes) -> None:
        """Send bytes (must be valid JSON)."""
        try:
            # Validate that bytes can be decoded as UTF-8 and parsed as JSON
            json_str = data.decode("utf-8")
            json.loads(json_str)
            self._queue_message(data)
            logger.debug(f"Queued JSON bytes: {len(data)} bytes")
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.error(f"Bytes are not valid JSON: {e}")
            raise TransportError(f"Bytes are not valid JSON: {e}")


class BytesTransport(Transport):
    """Transport for raw binary data."""

    def send_text(self, text: str) -> None:
        """Send text as UTF-8 bytes."""
        try:
            data = text.encode("utf-8")
            self._queue_message(data)
            logger.debug(f"Queued text as bytes: {len(data)} bytes")
        except UnicodeEncodeError as e:
            logger.error(f"Failed to encode text: {e}")
            raise TransportError(f"Failed to encode text: {e}")

    def send_json(self, obj: Dict[str, Any]) -> None:
        """Send JSON object as UTF-8 bytes."""
        try:
            json_str = json.dumps(obj, ensure_ascii=False)
            data = json_str.encode("utf-8")
            self._queue_message(data)
            logger.debug(f"Queued JSON as bytes: {len(data)} bytes")
        except (TypeError, ValueError, UnicodeEncodeError) as e:
            logger.error(f"Failed to serialize JSON: {e}")
            raise TransportError(f"Failed to serialize JSON: {e}")

    def send_bytes(self, data: bytes) -> None:
        """Send raw bytes."""
        self._queue_message(data)
        logger.debug(f"Queued raw bytes: {len(data)} bytes")


class TunTransport(Transport):
    """Transport for TUN/TAP interface integration."""

    def __init__(self, tun_device=None, max_queue_size: int = 1000):
        """
        Initialize TUN transport.

        Args:
            tun_device: TunDevice instance for TUN interface
            max_queue_size: Maximum size of outbound message queue
        """
        super().__init__(max_queue_size)
        self._tun_device = tun_device
        self._tun_reader_task: Optional[asyncio.Task] = None

        logger.info("TUN transport initialized")

    def attach_channel(self, channel: RTCDataChannel) -> None:
        """Attach data channel and start TUN reader."""
        super().attach_channel(channel)
        if self._tun_device:
            self._start_tun_reader()

    def _start_tun_reader(self) -> None:
        """Start background task to read from TUN interface."""
        if self._tun_device and (
            self._tun_reader_task is None or self._tun_reader_task.done()
        ):
            self._tun_reader_task = asyncio.create_task(self._tun_read_loop())
            logger.debug("Started TUN reader task")

    def _stop_tun_reader(self) -> None:
        """Stop TUN reader task."""
        if self._tun_reader_task and not self._tun_reader_task.done():
            self._tun_reader_task.cancel()
            logger.debug("Stopped TUN reader task")

    async def _tun_read_loop(self) -> None:
        """Background task to read packets from TUN interface."""
        try:
            while self._tun_device:
                try:
                    # This will be implemented by the TunDevice
                    packet = await self._tun_device.read_packet()
                    if packet:
                        self.send_bytes(packet)
                except Exception as e:
                    logger.error(f"Error reading from TUN: {e}")
                    await asyncio.sleep(0.1)  # Brief pause on error
        except asyncio.CancelledError:
            logger.debug("TUN reader loop cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in TUN reader loop: {e}")

    def _on_channel_message(self, message: Union[str, bytes]) -> None:
        """Handle incoming channel message and write to TUN."""
        try:
            if isinstance(message, str):
                data = message.encode("utf-8")
            else:
                data = message

            # Write to TUN interface
            if self._tun_device:
                asyncio.create_task(self._tun_device.write_packet(data))

            # Also call parent callback if registered
            if self._message_callback:
                self._message_callback(data)
        except Exception as e:
            logger.error(f"Error handling TUN channel message: {e}")

    def send_text(self, text: str) -> None:
        """Send text (not typical for TUN transport)."""
        logger.warning("Sending text over TUN transport - consider using send_bytes")
        data = text.encode("utf-8")
        self._queue_message(data)

    def send_json(self, obj: Dict[str, Any]) -> None:
        """Send JSON (not typical for TUN transport)."""
        logger.warning("Sending JSON over TUN transport - consider using send_bytes")
        json_str = json.dumps(obj, ensure_ascii=False)
        data = json_str.encode("utf-8")
        self._queue_message(data)

    def send_bytes(self, data: bytes) -> None:
        """Send raw bytes (typical for TUN transport)."""
        self._queue_message(data)
        logger.debug(f"Queued TUN packet: {len(data)} bytes")

    async def close(self) -> None:
        """Close transport and cleanup TUN resources."""
        logger.info("Closing TUN transport")

        self._shutdown_event.set()
        self._stop_tun_reader()

        if self._tun_reader_task and not self._tun_reader_task.done():
            self._tun_reader_task.cancel()
            try:
                await self._tun_reader_task
            except asyncio.CancelledError:
                pass

        await super().close()

        if self._tun_device:
            await self._tun_device.close()
            self._tun_device = None

        logger.info("TUN transport closed")


def create_transport(mode: str, **kwargs) -> Transport:
    """
    Factory function to create transport instances.

    Args:
        mode: Transport mode ("chat", "json", "bytes", "tun")
        **kwargs: Additional arguments for transport initialization

    Returns:
        Transport instance

    Raises:
        ValueError: If mode is not supported
    """
    if mode == "chat":
        return ChatTransport(**kwargs)
    elif mode == "json":
        return JsonTransport(**kwargs)
    elif mode == "bytes":
        return BytesTransport(**kwargs)
    elif mode == "tun":
        return TunTransport(**kwargs)
    else:
        raise ValueError(f"Unsupported transport mode: {mode}")
