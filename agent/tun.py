# mvp-agent/agent/tun.py
"""TUN/TAP interface support for Linux systems."""

import asyncio
import sys
if sys.platform == "linux":
    import fcntl
import logging
import os
import struct
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


class TunError(Exception):
    """TUN/TAP specific exception."""

    pass


class TunDevice:
    """TUN device interface for packet I/O."""

    # Linux TUN/TAP ioctl constants
    TUNSETIFF = 0x400454CA
    TUNGETIFF = 0x800454D2
    IFF_TUN = 0x0001
    IFF_TAP = 0x0002
    IFF_NO_PI = 0x1000
    IFF_TUN_EXCL = 0x8000

    def __init__(self, fd: int, name: str):
        """
        Initialize TUN device.

        Args:
            fd: File descriptor for TUN device
            name: Interface name
        """
        self.fd = fd
        self.name = name
        self._closed = False

        logger.info(f"TUN device initialized: {name} (fd={fd})")

    async def read_packet(self) -> Optional[bytes]:
        """
        Read a packet from TUN interface (non-blocking).

        Returns:
            Packet bytes if available, None otherwise
        """
        if self._closed:
            raise TunError("TUN device is closed")

        try:
            # Set non-blocking mode
            flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
            fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            # Try to read packet
            packet = os.read(self.fd, 65536)  # Max IP packet size
            logger.debug(f"Read packet from TUN: {len(packet)} bytes")
            return packet

        except BlockingIOError:
            # No data available
            return None
        except OSError as e:
            if e.errno == 9:  # Bad file descriptor
                raise TunError("TUN device file descriptor is invalid")
            raise TunError(f"Error reading from TUN: {e}")

    async def write_packet(self, packet: bytes) -> None:
        """
        Write packet to TUN interface.

        Args:
            packet: Packet bytes to write

        Raises:
            TunError: If write fails
        """
        if self._closed:
            raise TunError("TUN device is closed")

        try:
            # Write packet
            written = os.write(self.fd, packet)
            if written != len(packet):
                logger.warning(f"Partial write to TUN: {written}/{len(packet)} bytes")

            logger.debug(f"Wrote packet to TUN: {len(packet)} bytes")

        except OSError as e:
            if e.errno == 9:  # Bad file descriptor
                raise TunError("TUN device file descriptor is invalid")
            raise TunError(f"Error writing to TUN: {e}")

    async def read_loop(self, callback: Callable[[bytes], None]) -> None:
        """
        Continuous read loop with callback.

        Args:
            callback: Function to call with each packet
        """
        logger.info("Starting TUN read loop")

        try:
            while not self._closed:
                packet = await self.read_packet()
                if packet:
                    try:
                        callback(packet)
                    except Exception as e:
                        logger.error(f"Error in packet callback: {e}")
                else:
                    # No data available, yield control
                    await asyncio.sleep(0.001)  # 1ms sleep

        except TunError as e:
            logger.error(f"TUN read loop error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in TUN read loop: {e}")
        finally:
            logger.info("TUN read loop ended")

    def close(self) -> None:
        """Close TUN device."""
        if not self._closed:
            try:
                os.close(self.fd)
                logger.info(f"Closed TUN device: {self.name}")
            except OSError as e:
                logger.warning(f"Error closing TUN device: {e}")
            finally:
                self._closed = True

    async def close_async(self) -> None:
        """Async close for compatibility."""
        self.close()


def create_tun(name: str = "tun0") -> Tuple[int, str]:
    """
    Create TUN interface.

    Args:
        name: Desired interface name

    Returns:
        Tuple of (file_descriptor, actual_interface_name)

    Raises:
        TunError: If TUN creation fails
        OSError: If not running on Linux or missing permissions
    """
    # Check if running on Linux
    if os.name != "posix" or not os.path.exists("/dev/net/tun"):
        raise OSError(
            "TUN/TAP support requires Linux with /dev/net/tun. "
            "This feature is not available on Windows or macOS."
        )

    try:
        # Open TUN device
        tun_fd = os.open("/dev/net/tun", os.O_RDWR)
        logger.debug(f"Opened /dev/net/tun with fd={tun_fd}")

        # Prepare interface request structure
        ifr = struct.pack(
            "16sH", name.encode("ascii"), TunDevice.IFF_TUN | TunDevice.IFF_NO_PI
        )

        # Set interface name and flags
        fcntl.ioctl(tun_fd, TunDevice.TUNSETIFF, ifr)

        # Get actual interface name
        actual_name = ifr[:16].decode("ascii").rstrip("\x00")

        logger.info(f"Created TUN interface: {actual_name} (fd={tun_fd})")
        return tun_fd, actual_name

    except OSError as e:
        if tun_fd:
            try:
                os.close(tun_fd)
            except:
                pass

        if e.errno == 1:  # Operation not permitted
            raise TunError(
                "Permission denied creating TUN interface. "
                "Run with CAP_NET_ADMIN capability or as root."
            )
        elif e.errno == 16:  # Device or resource busy
            raise TunError(f"TUN interface '{name}' is already in use")
        else:
            raise TunError(f"Failed to create TUN interface: {e}")


def create_tap(name: str = "tap0") -> Tuple[int, str]:
    """
    Create TAP interface.

    Args:
        name: Desired interface name

    Returns:
        Tuple of (file_descriptor, actual_interface_name)

    Raises:
        TunError: If TAP creation fails
        OSError: If not running on Linux or missing permissions
    """
    # Check if running on Linux
    if os.name != "posix" or not os.path.exists("/dev/net/tun"):
        raise OSError(
            "TUN/TAP support requires Linux with /dev/net/tun. "
            "This feature is not available on Windows or macOS."
        )

    try:
        # Open TUN device
        tap_fd = os.open("/dev/net/tun", os.O_RDWR)
        logger.debug(f"Opened /dev/net/tun with fd={tap_fd}")

        # Prepare interface request structure
        ifr = struct.pack(
            "16sH", name.encode("ascii"), TunDevice.IFF_TAP | TunDevice.IFF_NO_PI
        )

        # Set interface name and flags
        fcntl.ioctl(tap_fd, TunDevice.TUNSETIFF, ifr)

        # Get actual interface name
        actual_name = ifr[:16].decode("ascii").rstrip("\x00")

        logger.info(f"Created TAP interface: {actual_name} (fd={tap_fd})")
        return tap_fd, actual_name

    except OSError as e:
        if tap_fd:
            try:
                os.close(tap_fd)
            except:
                pass

        if e.errno == 1:  # Operation not permitted
            raise TunError(
                "Permission denied creating TAP interface. "
                "Run with CAP_NET_ADMIN capability or as root."
            )
        elif e.errno == 16:  # Device or resource busy
            raise TunError(f"TAP interface '{name}' is already in use")
        else:
            raise TunError(f"Failed to create TAP interface: {e}")


def check_tun_support() -> bool:
    """
    Check if TUN/TAP support is available.

    Returns:
        True if TUN/TAP is supported, False otherwise
    """
    try:
        return (
            os.name == "posix"
            and os.path.exists("/dev/net/tun")
            and os.access("/dev/net/tun", os.R_OK | os.W_OK)
        )
    except Exception:
        return False


def get_interface_info(name: str) -> Optional[dict]:
    """
    Get information about a network interface.

    Args:
        name: Interface name

    Returns:
        Dictionary with interface info or None if not found
    """
    try:
        # Try to read from /proc/net/dev
        with open("/proc/net/dev", "r") as f:
            lines = f.readlines()

        for line in lines[2:]:  # Skip header lines
            parts = line.split(":")
            if len(parts) >= 2:
                iface_name = parts[0].strip()
                if iface_name == name:
                    stats = parts[1].split()
                    if len(stats) >= 16:
                        return {
                            "name": iface_name,
                            "rx_bytes": int(stats[0]),
                            "rx_packets": int(stats[1]),
                            "tx_bytes": int(stats[8]),
                            "tx_packets": int(stats[9]),
                        }

        return None

    except Exception as e:
        logger.warning(f"Could not get interface info for {name}: {e}")
        return None
