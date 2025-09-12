# mvp-agent/agent/core.py
"""WebRTC core connection management and peer session handling."""

import asyncio
import logging
from typing import Dict, Optional, Set

from aiortc import (
    RTCConfiguration,
    RTCDataChannel,
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.exceptions import InvalidStateError
from aiortc.sdp import candidate_from_sdp

from .config import AgentSettings, create_rtc_configuration
from .signaling import SignalingClient, MessageType
from .transport import Transport, create_transport
from .tun import TunDevice, create_tun

logger = logging.getLogger(__name__)


class PeerSession:
    """Represents a peer connection session."""

    def __init__(self, peer_id: str, pc: RTCPeerConnection, transport: Transport):
        """
        Initialize peer session.

        Args:
            peer_id: Peer identifier
            pc: RTCPeerConnection instance
            transport: Transport instance
        """
        self.peer_id = peer_id
        self.pc = pc
        self.transport = transport
        self.data_channel: Optional[RTCDataChannel] = None
        self.created_at = asyncio.get_event_loop().time()

        logger.info(f"Created peer session for {peer_id}")

    def is_connected(self) -> bool:
        """Check if peer connection is established."""
        return (
            self.pc.connectionState == "connected"
            and self.data_channel is not None
            and self.data_channel.readyState == "open"
        )

    def get_stats(self) -> Dict[str, any]:
        """Get session statistics."""
        return {
            "peer_id": self.peer_id,
            "connection_state": self.pc.connectionState,
            "ice_connection_state": self.pc.iceConnectionState,
            "ice_gathering_state": self.pc.iceGatheringState,
            "data_channel_state": (
                self.data_channel.readyState if self.data_channel else None
            ),
            "created_at": self.created_at,
            "uptime": asyncio.get_event_loop().time() - self.created_at,
        }


class AgentCore:
    """WebRTC agent core with peer connection management."""

    def __init__(self, settings: AgentSettings, signaling: SignalingClient):
        """
        Initialize agent core.

        Args:
            settings: Agent configuration settings
            signaling: Signaling client instance
        """
        self.settings = settings
        self.signaling = signaling
        self.peer_sessions: Dict[str, PeerSession] = {}
        self.rtc_config = create_rtc_configuration(settings.ice_servers)
        self._tasks: Set[asyncio.Task] = set()
        self._shutdown_event = asyncio.Event()

        logger.info(f"Agent core initialized for {settings.agent_id}")

    def _parse_candidate_type(self, candidate_sdp: str) -> Optional[str]:
        """Extract ICE candidate type from SDP attribute string."""
        try:
            # candidate line contains " typ <type>"
            parts = candidate_sdp.split()
            if "typ" in parts:
                idx = parts.index("typ")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        except Exception:
            pass
        return None

    def _log_ice_candidate(self, peer_id: str, candidate: RTCIceCandidate) -> None:
        """Log the ICE candidate type (host/srflx/relay/prflx)."""
        ctype = self._parse_candidate_type(candidate.candidate or "")
        if ctype:
            logger.info(f"Peer {peer_id} gathered ICE candidate type: {ctype}")
        else:
            logger.info(f"Peer {peer_id} gathered ICE candidate (type unknown)")

    def _log_selected_ice_pair(self, peer_id: str) -> None:
        """Log the selected ICE candidate pair types when available."""
        session = self.peer_sessions.get(peer_id)
        if not session:
            return
        try:
            # For data channels, go through SCTP -> DTLS -> ICE
            if (
                session.pc.sctp
                and session.pc.sctp.transport
                and session.pc.sctp.transport.transport
            ):
                ice_transport = session.pc.sctp.transport.transport
                pair = ice_transport.getSelectedCandidatePair()
                if pair and pair.local and pair.remote:
                    local_type = getattr(pair.local, "type", None)
                    remote_type = getattr(pair.remote, "type", None)
                    logger.info(
                        f"Peer {peer_id} selected ICE pair: local={local_type}, remote={remote_type}"
                    )
                    return
        except Exception as e:
            logger.debug(f"Peer {peer_id} could not get selected ICE pair: {e}")

    async def _on_ice_connection_state_change(self, peer_id: str) -> None:
        """Handle ICE connection state changes and log selected pair."""
        session = self.peer_sessions.get(peer_id)
        if not session:
            return
        state = session.pc.iceConnectionState
        logger.info(f"Peer {peer_id} ICE connection state: {state}")
        if state in ["connected", "completed"]:
            self._log_selected_ice_pair(peer_id)

    async def start(self) -> None:
        """Start agent core and begin processing signaling messages."""
        logger.info("Starting agent core")

        # Connect to signaling server
        await self.signaling.connect()

        # Start background task to process signaling messages
        self._tasks.add(asyncio.create_task(self._signaling_loop()))

        logger.info("Agent core started")

    async def _signaling_loop(self) -> None:
        """Background task to process incoming signaling messages."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(self.signaling.recv(), timeout=1.0)
                    await self._handle_incoming(message)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in signaling loop: {e}")
                    await asyncio.sleep(1.0)  # Brief pause on error
        except asyncio.CancelledError:
            logger.debug("Signaling loop cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in signaling loop: {e}")

    async def _handle_incoming(self, message: Dict[str, any]) -> None:
        """
        Handle incoming signaling message.

        Args:
            message: Signaling message dictionary
        """
        msg_type = message.get("type")
        from_id = message.get("from")
        to_id = message.get("to")

        logger.debug(f"Handling {msg_type} message from {from_id} to {to_id}")

        # Check if message is for us
        if to_id and to_id != self.settings.agent_id:
            logger.debug(f"Message not for us (to: {to_id}), ignoring")
            return

        try:
            if msg_type == MessageType.OFFER:
                await self._handle_offer(message)
            elif msg_type == MessageType.ANSWER:
                await self._handle_answer(message)
            elif msg_type == MessageType.CANDIDATE:
                await self._handle_candidate(message)
            elif msg_type == MessageType.BYE:
                await self._handle_bye(message)
            elif msg_type == MessageType.ERROR:
                await self._handle_error(message)
            else:
                logger.warning(f"Unknown message type: {msg_type}")
        except Exception as e:
            logger.error(f"Error handling {msg_type} message: {e}")

    async def _handle_offer(self, message: Dict[str, any]) -> None:
        """Handle incoming offer message."""
        from_id = message["from"]
        sdp = message["sdp"]

        logger.info(f"Received offer from {from_id}")

        # Create peer connection if not exists
        if from_id not in self.peer_sessions:
            await self._create_peer_session(from_id, is_offerer=False)

        session = self.peer_sessions[from_id]

        try:
            # Set remote description
            offer = RTCSessionDescription(sdp=sdp, type="offer")
            await session.pc.setRemoteDescription(offer)

            # Create answer
            answer = await session.pc.createAnswer()
            await session.pc.setLocalDescription(answer)

            # Send answer
            answer_msg = {
                "type": MessageType.ANSWER,
                "from": self.settings.agent_id,
                "to": from_id,
                "sdp": answer.sdp,
            }
            await self.signaling.send(answer_msg)

            logger.info(f"Sent answer to {from_id}")

        except Exception as e:
            logger.error(f"Error handling offer from {from_id}: {e}")
            await self._cleanup_session(from_id)

    async def _handle_answer(self, message: Dict[str, any]) -> None:
        """Handle incoming answer message."""
        from_id = message["from"]
        sdp = message["sdp"]

        logger.info(f"Received answer from {from_id}")

        if from_id not in self.peer_sessions:
            logger.warning(f"Received answer from unknown peer: {from_id}")
            return

        session = self.peer_sessions[from_id]

        try:
            # Set remote description
            answer = RTCSessionDescription(sdp=sdp, type="answer")
            await session.pc.setRemoteDescription(answer)

            logger.info(f"Set remote description for {from_id}")

        except Exception as e:
            logger.error(f"Error handling answer from {from_id}: {e}")
            await self._cleanup_session(from_id)

    async def _handle_candidate(self, message: Dict[str, any]) -> None:
        """Handle incoming ICE candidate message."""
        from_id = message["from"]
        cand_sdp = message.get("candidate")

        logger.debug(f"Received ICE candidate from {from_id}")

        if from_id not in self.peer_sessions:
            logger.warning(f"Received candidate from unknown peer: {from_id}")
            return

        session = self.peer_sessions[from_id]

        # If no candidate payload, treat as end-of-candidates from remote
        if cand_sdp is None:
            logger.info(f"{from_id}: remote ICE gathering complete")
            return

        try:
            # Support both legacy dict format and string SDP format
            if isinstance(cand_sdp, dict):
                cand_str = cand_sdp.get("candidate")
                sdp_mid = cand_sdp.get("sdpMid")
                sdp_mline_index = cand_sdp.get("sdpMLineIndex")
            else:
                cand_str = cand_sdp
                sdp_mid = message.get("sdpMid")
                sdp_mline_index = message.get("sdpMLineIndex")

            if not cand_str:
                logger.warning(f"{from_id}: received empty candidate string")
                return

            cand = candidate_from_sdp(cand_str)
            cand.sdpMid = sdp_mid
            cand.sdpMLineIndex = sdp_mline_index

            await session.pc.addIceCandidate(cand)
            logger.info(f"Applied candidate from {from_id}: {cand_str}")
        except Exception as e:
            logger.error(f"Failed to apply candidate from {from_id}: {cand_sdp} ({e})")

    async def _handle_bye(self, message: Dict[str, any]) -> None:
        """Handle connection termination message."""
        from_id = message["from"]

        logger.info(f"Received bye from {from_id}")
        await self._cleanup_session(from_id)

    async def _handle_error(self, message: Dict[str, any]) -> None:
        """Handle error message."""
        error_msg = message.get("error", "Unknown error")
        from_id = message.get("from", "unknown")

        logger.error(f"Received error from {from_id}: {error_msg}")

    async def connect_to(self, peer_id: str) -> None:
        """
        Initiate connection to peer.

        Args:
            peer_id: Target peer identifier
        """
        logger.info(f"Connecting to peer: {peer_id}")

        # Create peer session
        await self._create_peer_session(peer_id, is_offerer=True)
        session = self.peer_sessions[peer_id]

        try:
            # Create data channel
            data_channel = session.pc.createDataChannel(
                self.settings.data_channel_label, ordered=True
            )
            session.data_channel = data_channel
            session.transport.attach_channel(data_channel)

            # Set up ICE candidate handler
            def on_ice_candidate(candidate):
                asyncio.create_task(self._send_candidate(peer_id, candidate))
                if candidate is not None:
                    self._log_ice_candidate(peer_id, candidate)

            session.pc.on("icecandidate", on_ice_candidate)

            # Send end-of-candidates when gathering completes
            def on_ice_gathering_state_change():
                if session.pc.iceGatheringState == "complete":
                    asyncio.create_task(self._send_candidate(peer_id, None))

            session.pc.on("icegatheringstatechange", on_ice_gathering_state_change)

            # ICE connection state handler
            def on_ice_connection_state_change():
                asyncio.create_task(self._on_ice_connection_state_change(peer_id))

            session.pc.on("iceconnectionstatechange", on_ice_connection_state_change)

            # Set up connection state handler
            def on_connection_state_change():
                asyncio.create_task(self._on_connection_state_change(peer_id))

            session.pc.on("connectionstatechange", on_connection_state_change)

            # Create offer
            offer = await session.pc.createOffer()
            await session.pc.setLocalDescription(offer)

            # Send offer
            offer_msg = {
                "type": MessageType.OFFER,
                "from": self.settings.agent_id,
                "to": peer_id,
                "sdp": offer.sdp,
            }
            await self.signaling.send(offer_msg)

            logger.info(f"Sent offer to {peer_id}")

        except Exception as e:
            logger.error(f"Error connecting to {peer_id}: {e}")
            await self._cleanup_session(peer_id)
            raise

    async def _create_peer_session(self, peer_id: str, is_offerer: bool) -> None:
        """Create new peer session."""
        logger.info(f"Creating peer session for {peer_id} (offerer: {is_offerer})")

        # Create peer connection
        pc = RTCPeerConnection(self.rtc_config)

        # Create transport
        transport = create_transport(self.settings.mode)

        # Create session
        session = PeerSession(peer_id, pc, transport)
        self.peer_sessions[peer_id] = session

        # Set up data channel handler for answerer
        if not is_offerer:

            def on_data_channel(channel):
                logger.info(f"Received data channel from {peer_id}: {channel.label}")
                session.data_channel = channel
                session.transport.attach_channel(channel)

            pc.on("datachannel", on_data_channel)

        # Set up connection state handler
        def on_connection_state_change():
            asyncio.create_task(self._on_connection_state_change(peer_id))

        pc.on("connectionstatechange", on_connection_state_change)

        # Set up ICE events
        def on_ice_candidate(candidate):
            asyncio.create_task(self._send_candidate(peer_id, candidate))
            if candidate is not None:
                self._log_ice_candidate(peer_id, candidate)

        pc.on("icecandidate", on_ice_candidate)

        def on_ice_gathering_state_change():
            if pc.iceGatheringState == "complete":
                asyncio.create_task(self._send_candidate(peer_id, None))

        pc.on("icegatheringstatechange", on_ice_gathering_state_change)

        def on_ice_connection_state_change():
            asyncio.create_task(self._on_ice_connection_state_change(peer_id))

        pc.on("iceconnectionstatechange", on_ice_connection_state_change)

        logger.info(f"Created peer session for {peer_id}")

    async def _send_candidate(self, peer_id: str, candidate: RTCIceCandidate) -> None:
        """Send ICE candidate to peer."""
        try:
            if candidate is None:
                logger.info(f"{peer_id}: ICE gathering complete")
                candidate_msg = {
                    "type": MessageType.CANDIDATE,
                    "from": self.settings.agent_id,
                    "to": peer_id,
                    "candidate": None,
                }
                await self.signaling.send(candidate_msg)
                return

            cand_sdp = getattr(candidate, "to_sdp", None)
            cand_sdp = cand_sdp() if callable(cand_sdp) else candidate.candidate

            candidate_msg = {
                "type": MessageType.CANDIDATE,
                "from": self.settings.agent_id,
                "to": peer_id,
                "candidate": cand_sdp,
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
            }

            await self.signaling.send(candidate_msg)
            logger.info(f"Sent candidate to {peer_id}: {cand_sdp}")

        except Exception as e:
            logger.error(f"Error sending candidate to {peer_id}: {e}")

    async def _on_connection_state_change(self, peer_id: str) -> None:
        """Handle peer connection state change."""
        if peer_id not in self.peer_sessions:
            return

        session = self.peer_sessions[peer_id]
        state = session.pc.connectionState

        logger.info(f"Peer {peer_id} connection state: {state}")

        if state in ["failed", "closed", "disconnected"]:
            logger.warning(f"Peer {peer_id} connection {state}, cleaning up")
            await self._cleanup_session(peer_id)

    async def _cleanup_session(self, peer_id: str) -> None:
        """Clean up peer session."""
        if peer_id not in self.peer_sessions:
            return

        logger.info(f"Cleaning up session for {peer_id}")

        session = self.peer_sessions[peer_id]

        try:
            # Close transport
            await session.transport.close()

            # Close peer connection
            await session.pc.close()

        except Exception as e:
            logger.error(f"Error cleaning up session for {peer_id}: {e}")
        finally:
            self.peer_sessions.pop(peer_id, None)
            logger.info(f"Cleaned up session for {peer_id}")

    def get_channel(self, peer_id: Optional[str] = None) -> Optional[RTCDataChannel]:
        """
        Get data channel for peer.

        Args:
            peer_id: Peer identifier, None for first available

        Returns:
            RTCDataChannel instance or None
        """
        if peer_id:
            session = self.peer_sessions.get(peer_id)
            return session.data_channel if session else None
        else:
            # Return first available channel
            for session in self.peer_sessions.values():
                if session.data_channel:
                    return session.data_channel
            return None

    def get_session(self, peer_id: str) -> Optional[PeerSession]:
        """Get peer session by ID."""
        return self.peer_sessions.get(peer_id)

    def get_all_sessions(self) -> Dict[str, PeerSession]:
        """Get all peer sessions."""
        return self.peer_sessions.copy()

    def get_stats(self) -> Dict[str, any]:
        """Get agent core statistics."""
        return {
            "agent_id": self.settings.agent_id,
            "peer_count": len(self.peer_sessions),
            "peers": {
                peer_id: session.get_stats()
                for peer_id, session in self.peer_sessions.items()
            },
        }

    async def stop(self) -> None:
        """Stop agent core and cleanup resources."""
        logger.info("Stopping agent core")

        self._shutdown_event.set()

        # Cancel all background tasks
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

        # Clean up all peer sessions
        peer_ids = list(self.peer_sessions.keys())
        for peer_id in peer_ids:
            await self._cleanup_session(peer_id)

        # Close signaling connection
        await self.signaling.close()

        logger.info("Agent core stopped")
