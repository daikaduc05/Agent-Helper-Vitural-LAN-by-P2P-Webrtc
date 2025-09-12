# MVP Agent - WebRTC Data Channel Agent

A production-ready Python WebRTC data channel agent with clean separation between control-plane (WebSocket signaling) and data-plane (DataChannel transports), designed for extensibility to TUN/TAP VPN-like functionality.

## Features

- **WebRTC Data Channels**: Full WebRTC peer-to-peer data channel support
- **Modular Architecture**: Clean separation of signaling, transport, and core components
- **Multiple Transport Modes**: Chat, JSON, raw bytes, and TUN/TAP support
- **Production Ready**: Comprehensive error handling, logging, and graceful shutdown
- **Async/Await**: Fully asynchronous Python 3.10+ implementation
- **Type Safety**: Complete type hints and Pydantic validation
- **Testing**: Unit tests with mocked dependencies
- **CLI Interface**: Command-line tools for easy operation

## Architecture

### Control Plane vs Data Plane

The agent implements a clean separation between:

- **Control Plane**: WebSocket signaling for WebRTC offer/answer/ICE candidate exchange
- **Data Plane**: WebRTC data channels for actual data transport

```
┌─────────────────┐    WebSocket     ┌─────────────────┐
│   Agent A       │◄────────────────►│  Signaling      │
│                 │   (Control)      │  Server         │
│  ┌─────────────┐│                  │                 │
│  │ Signaling   ││                  └─────────────────┘
│  │ Client      ││
│  └─────────────┘│
│                 │
│  ┌─────────────┐│    WebRTC        ┌─────────────────┐
│  │ Agent Core  ││◄────────────────►│   Agent B       │
│  │             ││   (Data)         │                 │
│  │ ┌─────────┐ ││                  │  ┌─────────────┐│
│  │ │Transport│ ││                  │  │ Agent Core  ││
│  │ └─────────┘ ││                  │  │             ││
│  └─────────────┘│                  │  │ ┌─────────┐ ││
└─────────────────┘                  │  │ │Transport│ ││
                                     │  │ └─────────┘ ││
                                     │  └─────────────┘│
                                     └─────────────────┘
```

### Component Overview

- **`agent/config.py`**: Configuration management with environment and file support
- **`agent/signaling.py`**: WebSocket signaling client with reconnection and reliability
- **`agent/core.py`**: WebRTC connection management and peer session handling
- **`agent/transport.py`**: Data transport abstraction layer
- **`agent/tun.py`**: TUN/TAP interface support for VPN-like functionality
- **`cli.py`**: Command-line interface for agent operations

## Installation

### Prerequisites

- Python 3.10 or higher
- Linux (for TUN/TAP support)
- Root privileges or `CAP_NET_ADMIN` capability (for TUN/TAP)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Environment Setup

Create a `.env` file with required configuration:

```bash
# Required
AGENT_ID=your-unique-agent-id
SIGNALING_URL=wss://your-signaling-server.com

# Optional
SIGNALING_TOKEN=your-auth-token
MODE=chat
DATA_CHANNEL_LABEL=mvp

# ICE servers (optional)
ICE_URL=stun:stun.l.google.com:19302
ICE_USERNAME=optional-username
ICE_CREDENTIAL=optional-credential

# Multiple ICE servers (CSV)
ICE_URLS=stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302
```

## Usage

### Command Line Interface

#### Connect to a Peer

```bash
python cli.py connect peer-123
```

#### Listen for Incoming Connections

```bash
python cli.py listen
```

#### Check Status

```bash
python cli.py status
```

### Transport Modes

#### Chat Mode (Default)

```bash
export MODE=chat
python cli.py connect peer-123
```

Interactive text chat with UTF-8 encoding.

#### JSON Mode

```bash
export MODE=json
python cli.py connect peer-123
```

Structured JSON message exchange.

#### Bytes Mode

```bash
export MODE=bytes
python cli.py connect peer-123
```

Raw binary data transfer.

#### TUN Mode (Linux)

```bash
export MODE=tun
sudo python cli.py connect peer-123
```

VPN-like functionality with TUN interface.

### Examples

#### Basic Chat Example

**Terminal 1 (Answerer):**

```bash
export AGENT_ID=alice
export SIGNALING_URL=wss://your-server.com
export MODE=chat
python examples/chat_answer.py
```

**Terminal 2 (Offerer):**

```bash
export AGENT_ID=bob
export SIGNALING_URL=wss://your-server.com
export MODE=chat
python examples/chat_offer.py alice
```

#### TUN/VPN Example

**Terminal 1 (Answerer):**

```bash
export AGENT_ID=server
export SIGNALING_URL=wss://your-server.com
export MODE=tun
sudo python examples/lan_demo.py answer
```

**Terminal 2 (Offerer):**

```bash
export AGENT_ID=client
export SIGNALING_URL=wss://your-server.com
export MODE=tun
sudo python examples/lan_demo.py offer server
```

After starting, configure the TUN interfaces:

```bash
# On server (10.0.0.1)
sudo ip addr add 10.0.0.1/24 dev mvp-tun1
sudo ip link set mvp-tun1 up

# On client (10.0.0.2)
sudo ip addr add 10.0.0.2/24 dev mvp-tun0
sudo ip link set mvp-tun0 up

# Test connectivity
ping 10.0.0.2  # From server
ping 10.0.0.1  # From client
```

## Configuration

### Environment Variables

| Variable             | Required | Default | Description                                     |
| -------------------- | -------- | ------- | ----------------------------------------------- |
| `AGENT_ID`           | Yes      | -       | Unique agent identifier                         |
| `SIGNALING_URL`      | Yes      | -       | WebSocket signaling server URL                  |
| `SIGNALING_TOKEN`    | No       | -       | Optional authentication token                   |
| `MODE`               | No       | `chat`  | Transport mode (`chat`, `json`, `bytes`, `tun`) |
| `DATA_CHANNEL_LABEL` | No       | `mvp`   | WebRTC data channel label                       |
| `ICE_URL`            | No       | -       | Single ICE server URL                           |
| `ICE_URLS`           | No       | -       | Multiple ICE server URLs (CSV)                  |
| `ICE_USERNAME`       | No       | -       | ICE server username                             |
| `ICE_CREDENTIAL`     | No       | -       | ICE server credential                           |

### Configuration Files

Support for YAML and JSON configuration files:

```yaml
# config.yaml
agent_id: "my-agent"
signaling_url: "wss://signaling.example.com"
signaling_token: "secret-token"
mode: "chat"
ice_servers:
  - urls: "stun:stun.l.google.com:19302"
  - urls: "turn:turn.example.com:3478"
    username: "user"
    credential: "pass"
```

```bash
export AGENT_CONFIG=config.yaml
python cli.py connect peer-123
```

## API Reference

### Core Classes

#### `AgentSettings`

Configuration container with validation:

```python
from agent import load_settings

settings = load_settings()
print(f"Agent ID: {settings.agent_id}")
print(f"Mode: {settings.mode}")
```

#### `SignalingClient`

WebSocket signaling client:

```python
from agent import SignalingClient

signaling = SignalingClient(settings)
await signaling.connect()
await signaling.send({"type": "offer", "sdp": "..."})
message = await signaling.recv()
```

#### `AgentCore`

WebRTC connection manager:

```python
from agent import AgentCore

core = AgentCore(settings, signaling)
await core.start()
await core.connect_to("peer-123")
channel = core.get_channel("peer-123")
```

#### `Transport`

Data transport abstraction:

```python
from agent import create_transport

transport = create_transport("chat")
transport.attach_channel(data_channel)
transport.send_text("Hello, World!")
```

### Transport Types

- **`ChatTransport`**: UTF-8 text messages
- **`JsonTransport`**: JSON object serialization
- **`BytesTransport`**: Raw binary data
- **`TunTransport`**: TUN/TAP interface integration

## Signaling Protocol

The agent uses a simple JSON-based signaling protocol over WebSocket:

### Message Types

#### Register

```json
{
  "type": "register",
  "id": "agent-123",
  "token": "optional-token"
}
```

#### Offer

```json
{
  "type": "offer",
  "from": "alice",
  "to": "bob",
  "sdp": "v=0\r\no=alice..."
}
```

#### Answer

```json
{
  "type": "answer",
  "from": "bob",
  "to": "alice",
  "sdp": "v=0\r\no=bob..."
}
```

#### ICE Candidate

```json
{
  "type": "candidate",
  "from": "alice",
  "to": "bob",
  "candidate": {
    "candidate": "candidate:1 1 UDP 2113667326 192.168.1.100 54400 typ host",
    "sdpMid": "0",
    "sdpMLineIndex": 0
  }
}
```

#### Bye

```json
{
  "type": "bye",
  "from": "alice",
  "to": "bob"
}
```

## Testing

Run the test suite:

```bash
pytest tests/
```

Run with verbose output:

```bash
pytest -v tests/
```

## Development

### Project Structure

```
mvp-agent/
├── agent/                 # Core agent package
│   ├── __init__.py       # Package exports
│   ├── config.py         # Configuration management
│   ├── core.py           # WebRTC connection management
│   ├── signaling.py      # WebSocket signaling client
│   ├── transport.py      # Data transport abstraction
│   └── tun.py            # TUN/TAP interface support
├── cli.py                # Command-line interface
├── examples/             # Example scripts
│   ├── chat_offer.py     # Chat offerer example
│   ├── chat_answer.py    # Chat answerer example
│   └── lan_demo.py       # TUN/VPN demo
├── tests/                # Unit tests
│   └── test_core.py      # Core functionality tests
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

### Adding New Transport Types

1. Create a new transport class inheriting from `Transport`
2. Implement required methods: `send_text()`, `send_json()`, `send_bytes()`
3. Add to `create_transport()` factory function
4. Update configuration validation

### Adding New Signaling Features

1. Define new message types in `MessageType` enum
2. Create Pydantic models for message validation
3. Add handlers in `AgentCore._handle_incoming()`
4. Update signaling protocol documentation

## Troubleshooting

### Common Issues

#### Connection Timeout

- Check signaling server URL and connectivity
- Verify ICE server configuration
- Check firewall settings for WebRTC ports

#### TUN Interface Creation Fails

- Ensure running on Linux with `/dev/net/tun`
- Check for root privileges or `CAP_NET_ADMIN`
- Verify interface name is not already in use

#### WebRTC Connection Fails

- Check ICE server configuration
- Verify network connectivity between peers
- Review signaling server logs for errors

### Debugging

Enable verbose logging:

```bash
python cli.py --verbose connect peer-123
```

Or set log level in code:

```python
import logging
logging.getLogger().setLevel(logging.DEBUG)
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## Roadmap

- [ ] WebRTC statistics and monitoring
- [ ] Multiple data channel support
- [ ] Advanced TUN/TAP features (routing, NAT)
- [ ] Mobile platform support
- [ ] Web-based management interface
- [ ] Docker containerization
- [ ] Kubernetes deployment examples
