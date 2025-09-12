# mvp-agent/agent/config.py
"""Agent configuration management with environment and file support."""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class AgentSettings(BaseModel):
    """Agent configuration settings with validation."""

    agent_id: str = Field(..., description="Unique agent identifier")
    signaling_url: str = Field(..., description="WebSocket signaling server URL")
    signaling_token: Optional[str] = Field(
        None, description="Optional authentication token"
    )
    ice_servers: List[Dict[str, Any]] = Field(
        default_factory=list, description="ICE servers configuration"
    )
    data_channel_label: str = Field(default="mvp", description="Data channel label")
    mode: Literal["chat", "json", "bytes", "tun"] = Field(
        default="chat", description="Transport mode"
    )

    @validator("signaling_url")
    def validate_signaling_url(cls, v: str) -> str:
        """Validate signaling URL format."""
        if not v.startswith(("ws://", "wss://")):
            raise ValueError("Signaling URL must start with ws:// or wss://")
        return v

    @validator("ice_servers")
    def validate_ice_servers(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate ICE servers format."""
        for server in v:
            if "urls" not in server:
                raise ValueError("ICE server must have 'urls' field")
            if not isinstance(server["urls"], (str, list)):
                raise ValueError("ICE server 'urls' must be string or list")
        return v

    class Config:
        """Pydantic configuration."""

        env_prefix = "AGENT_"
        case_sensitive = False


def load_settings(
    config_file: Optional[Union[str, Path]] = None,
    env_file: Optional[Union[str, Path]] = None,
) -> AgentSettings:
    """
    Load agent settings from environment variables and optional config file.

    Args:
        config_file: Optional path to YAML/JSON config file
        env_file: Optional path to .env file

    Returns:
        AgentSettings instance with loaded configuration

    Raises:
        ValueError: If required settings are missing or invalid
        FileNotFoundError: If config file is specified but doesn't exist
    """
    logger.info("Loading agent settings")

    # Load environment variables from .env file if specified
    if env_file:
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"Loaded environment from {env_path}")
        else:
            logger.warning(f"Environment file not found: {env_path}")
    else:
        # Try default .env file
        default_env = Path(".env")
        if default_env.exists():
            load_dotenv(default_env)
            logger.info("Loaded environment from .env")

    # Load config file if specified
    config_data: Dict[str, Any] = {}
    if config_file:
        config_path = Path(config_file)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r") as f:
            if config_path.suffix.lower() in [".yaml", ".yml"]:
                config_data = yaml.safe_load(f)
            elif config_path.suffix.lower() == ".json":
                import json

                config_data = json.load(f)
            else:
                raise ValueError(
                    f"Unsupported config file format: {config_path.suffix}"
                )

        logger.info(f"Loaded config from {config_path}")

    # Build settings from environment variables
    env_data: Dict[str, Any] = {}

    # Required fields
    agent_id = os.getenv("AGENT_ID")
    if not agent_id:
        raise ValueError("AGENT_ID environment variable is required")
    env_data["agent_id"] = agent_id

    signaling_url = os.getenv("SIGNALING_URL")
    if not signaling_url:
        raise ValueError("SIGNALING_URL environment variable is required")
    env_data["signaling_url"] = signaling_url

    # Optional fields
    if token := os.getenv("SIGNALING_TOKEN"):
        env_data["signaling_token"] = token

    if mode := os.getenv("MODE"):
        env_data["mode"] = mode

    if label := os.getenv("DATA_CHANNEL_LABEL"):
        env_data["data_channel_label"] = label

    # Build ICE servers from environment
    ice_servers = _build_ice_servers_from_env()
    if ice_servers:
        env_data["ice_servers"] = ice_servers

    # Merge config file data with environment data (env takes precedence)
    merged_data = {**config_data, **env_data}

    try:
        settings = AgentSettings(**merged_data)
        logger.info(f"Loaded settings for agent: {settings.agent_id}")
        logger.info(f"Signaling URL: {settings.signaling_url}")
        logger.info(f"Mode: {settings.mode}")
        logger.info(f"ICE servers: {len(settings.ice_servers)} configured")
        return settings
    except Exception as e:
        logger.error(f"Failed to create AgentSettings: {e}")
        raise


def _build_ice_servers_from_env() -> List[Dict[str, Any]]:
    """Build ICE servers list from environment variables."""
    ice_servers = []

    # Single ICE server from individual env vars
    ice_url = os.getenv("ICE_URL")
    if ice_url:
        server = {"urls": ice_url}
        if username := os.getenv("ICE_USERNAME"):
            server["username"] = username
        if credential := os.getenv("ICE_CREDENTIAL"):
            server["credential"] = credential
        ice_servers.append(server)

    # Multiple ICE servers from CSV
    ice_urls = os.getenv("ICE_URLS")
    if ice_urls:
        urls = [url.strip() for url in ice_urls.split(",") if url.strip()]
        for url in urls:
            server = {"urls": url}
            if username := os.getenv("ICE_USERNAME"):
                server["username"] = username
            if credential := os.getenv("ICE_CREDENTIAL"):
                server["credential"] = credential
            ice_servers.append(server)

    return ice_servers


def create_rtc_configuration(ice_servers: List[Dict[str, Any]]) -> "RTCConfiguration":
    """
    Create aiortc RTCConfiguration from ICE servers list.

    Args:
        ice_servers: List of ICE server configurations

    Returns:
        RTCConfiguration instance for aiortc
    """
    try:
        from aiortc import RTCConfiguration, RTCIceServer

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
    except ImportError:
        logger.warning("aiortc not available, cannot create RTCConfiguration")
        return None
