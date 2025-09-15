# mvp-agent/agent/signaling.py
"""WebSocket signaling client for control-plane communication."""

import asyncio
import json
import logging
import random
from typing import Any, Dict, Optional, Union
from enum import Enum

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
from pydantic import BaseModel, Field

from .config import AgentSettings

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Signaling message types."""

    REGISTER = "register"
    OFFER = "offer"
    ANSWER = "answer"
    CANDIDATE = "candidate"
    BYE = "bye"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


class SignalingMessage(BaseModel):
    """Base signaling message with validation."""

    type: MessageType
    from_id: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    class Config:
        use_enum_values = True
        populate_by_name = True


class OfferMessage(SignalingMessage):
    """WebRTC offer message."""

    type: MessageType = MessageType.OFFER
    sdp: str
    from_id: str = Field(..., alias="from")
    to: str


class AnswerMessage(SignalingMessage):
    """WebRTC answer message."""

    type: MessageType = MessageType.ANSWER
    sdp: str
    from_id: str = Field(..., alias="from")
    to: str


class CandidateMessage(SignalingMessage):
    """ICE candidate message. 'candidate' may be None for end-of-candidates."""

    type: MessageType = MessageType.CANDIDATE
    candidate: Optional[Dict[str, Any]] = None
    from_id: str = Field(..., alias="from")
    to: str


class ByeMessage(SignalingMessage):
    """Connection termination message."""

    type: MessageType = MessageType.BYE
    from_id: str = Field(..., alias="from")
    to: str


class ErrorMessage(SignalingMessage):
    """Error message."""

    type: MessageType = MessageType.ERROR
    error: str
    from_id: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None


class SignalingError(Exception):
    """Signaling-specific exception."""

    pass


class SignalingClient:
    """WebSocket signaling client with reconnection and reliability features."""

    def __init__(
        self,
        settings: AgentSettings,
        heartbeat_interval: float = 30.0,
        max_reconnect_attempts: int = 10,
        initial_reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ):
        """
        Initialize signaling client.

        Args:
            settings: Agent configuration settings
            heartbeat_interval: Heartbeat interval in seconds
            max_reconnect_attempts: Maximum reconnection attempts
            initial_reconnect_delay: Initial reconnection delay in seconds
            max_reconnect_delay: Maximum reconnection delay in seconds
        """
        self.settings = settings
        self.heartbeat_interval = heartbeat_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.initial_reconnect_delay = initial_reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        self._websocket: Optional[websockets.WebSocketServerProtocol] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._message_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._outbox_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._tasks: set[asyncio.Task] = set()
        self._shutdown_event = asyncio.Event()

        logger.info(f"Signaling client initialized for {settings.agent_id}")

    @property
    def connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._websocket is not None

    @property
    def message_queue(self) -> asyncio.Queue[Dict[str, Any]]:
        """Get the incoming message queue."""
        return self._message_queue

    async def connect(self) -> None:
        """
        Connect to signaling server with automatic reconnection.

        Raises:
            SignalingError: If connection fails after max attempts
        """
        logger.info(f"Connecting to signaling server: {self.settings.signaling_url}")

        while self._reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self._do_connect()
                self._reconnect_attempts = 0
                logger.info("Successfully connected to signaling server")
                return

            except Exception as e:
                self._reconnect_attempts += 1
                logger.warning(
                    f"Connection attempt {self._reconnect_attempts} failed: {e}"
                )

                if self._reconnect_attempts >= self.max_reconnect_attempts:
                    logger.error("Max reconnection attempts reached")
                    raise SignalingError(
                        f"Failed to connect after {self.max_reconnect_attempts} attempts"
                    )

                # Exponential backoff with jitter
                delay = min(
                    self.initial_reconnect_delay
                    * (2 ** (self._reconnect_attempts - 1)),
                    self.max_reconnect_delay,
                )
                jitter = random.uniform(0.1, 0.3) * delay
                total_delay = delay + jitter

                logger.info(f"Reconnecting in {total_delay:.1f} seconds...")
                await asyncio.sleep(total_delay)

    async def _do_connect(self) -> None:
        """Perform actual WebSocket connection."""
        headers = {}
        if self.settings.signaling_token:
            headers["Authorization"] = f"Bearer {self.settings.signaling_token}"

        self._websocket = await websockets.connect(
            self.settings.signaling_url,
            extra_headers=headers,
            ping_interval=None,  # We handle our own heartbeat
            ping_timeout=None,
            close_timeout=10,
        )

        self._connected = True

        # Start background tasks
        self._tasks.add(asyncio.create_task(self._message_reader()))
        self._tasks.add(asyncio.create_task(self._message_sender()))
        self._tasks.add(asyncio.create_task(self._heartbeat()))

        # Send registration message
        await self._send_register()

        # Process any queued messages
        await self._flush_outbox()

    async def _send_register(self) -> None:
        """Send registration message to server."""
        register_msg = {
            "type": MessageType.REGISTER,
            "id": self.settings.agent_id,
            "token": self.settings.signaling_token,
        }
        await self._send_raw(register_msg)
        logger.info(f"Sent registration for agent: {self.settings.agent_id}")

    async def _message_reader(self) -> None:
        """Background task to read messages from WebSocket."""
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    validated_msg = self._validate_message(data)
                    await self._message_queue.put(validated_msg)
                    logger.debug(f"Received message: {validated_msg['type']}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON received: {e}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
        except ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self._connected = False
        except Exception as e:
            logger.error(f"Error in message reader: {e}")
            self._connected = False

    async def _message_sender(self) -> None:
        """Background task to send queued messages."""
        try:
            while self.connected:
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(
                        self._outbox_queue.get(), timeout=1.0
                    )
                    await self._send_raw(message)
                    self._outbox_queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error sending message: {e}")
        except Exception as e:
            logger.error(f"Error in message sender: {e}")

    async def _heartbeat(self) -> None:
        """Background task for heartbeat/ping."""
        try:
            while self.connected and not self._shutdown_event.is_set():
                await asyncio.sleep(self.heartbeat_interval)
                if self.connected:
                    ping_msg = {"type": MessageType.PING}
                    await self._send_raw(ping_msg)
                    logger.debug("Sent heartbeat ping")
        except Exception as e:
            logger.error(f"Error in heartbeat: {e}")

    async def _flush_outbox(self) -> None:
        """Flush any queued outgoing messages."""
        while not self._outbox_queue.empty():
            try:
                message = self._outbox_queue.get_nowait()
                await self._send_raw(message)
                self._outbox_queue.task_done()
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.error(f"Error flushing outbox: {e}")

    async def _send_raw(self, message: Dict[str, Any]) -> None:
        """Send raw message over WebSocket."""
        if not self.connected or not self._websocket:
            raise SignalingError("Not connected to signaling server")

        try:
            await self._websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise SignalingError(f"Failed to send message: {e}")

    def _validate_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate incoming message structure."""
        try:
            msg_type = data.get("type")
            if not msg_type:
                raise ValueError("Message missing 'type' field")

            # Validate based on message type
            if msg_type == MessageType.OFFER:
                OfferMessage(**data)
            elif msg_type == MessageType.ANSWER:
                AnswerMessage(**data)
            elif msg_type == MessageType.CANDIDATE:
                CandidateMessage(**data)
            elif msg_type == MessageType.BYE:
                ByeMessage(**data)
            elif msg_type == MessageType.ERROR:
                ErrorMessage(**data)
            elif msg_type in [MessageType.PING, MessageType.PONG]:
                # Simple ping/pong messages
                pass
            else:
                logger.warning(f"Unknown message type: {msg_type}")

            return data
        except Exception as e:
            logger.error(f"Message validation failed: {e}")
            raise ValueError(f"Invalid message format: {e}")

    async def send(self, message: Dict[str, Any]) -> None:
        """
        Send message to signaling server.

        Args:
            message: Message dictionary to send

        Raises:
            SignalingError: If not connected and message cannot be queued
        """
        if self.connected:
            await self._send_raw(message)
        else:
            # Queue message for later sending
            await self._outbox_queue.put(message)
            logger.debug("Queued message for later sending")

    async def recv(self) -> Dict[str, Any]:
        """
        Receive message from signaling server.

        Returns:
            Next message from the queue

        Raises:
            asyncio.TimeoutError: If no message received within timeout
        """
        return await self._message_queue.get()

    async def recv_nowait(self) -> Optional[Dict[str, Any]]:
        """
        Try to receive message without blocking.

        Returns:
            Message if available, None otherwise
        """
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def close(self) -> None:
        """Gracefully close signaling connection."""
        logger.info("Closing signaling client")

        self._shutdown_event.set()
        self._connected = False

        # Cancel all background tasks
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

        # Close WebSocket connection
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            finally:
                self._websocket = None

        logger.info("Signaling client closed")
