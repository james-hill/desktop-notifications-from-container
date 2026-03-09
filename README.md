# Desktop Notifications from Container

A lightweight HTTP server that allows Docker containers to send desktop notifications to the host. Containers send a simple JSON POST request; the host displays a native notification.

Supports **macOS**, **Linux**, and **Windows**.

## Architecture

```
┌──────────────────────┐             HTTP POST             ┌──────────────────────┐
│   Docker Container   │  ─────────────────────────────►   │   notify_server.py   │
│                      │  host.docker.internal:6789/notify │   (host machine)     │
└──────────────────────┘                                   └──────────┬───────────┘
                                                                      │
                                                          osascript / notify-send
                                                              / PowerShell
                                                                      │
                                                                      ▼
                                                           ┌──────────────────┐
                                                           │     Desktop      │
                                                           │   Notification   │
                                                           └──────────────────┘
```

The server is a single Python file with no external dependencies. It uses the standard library `http.server` to listen on `127.0.0.1:6789` and dispatches to the platform's native notification system:

| Platform | Method | Sound support |
|----------|--------|---------------|
| macOS    | `osascript` (AppleScript) | Yes |
| Linux    | `notify-send` (libnotify) | No (depends on desktop environment) |
| Windows  | PowerShell + .NET `System.Windows.Forms` | Yes |

Containers reach the host via Docker's `host.docker.internal` hostname or by forwarding the port.

## Requirements

- Python 3.10+
- **macOS**: no extra dependencies
- **Linux**: `notify-send` (usually pre-installed with `libnotify`)
- **Windows**: PowerShell (built-in)

## Installation

Clone the repo and run the install script for your platform:

### macOS / Linux

```bash
git clone <repo-url>
cd desktop-notifications-from-container
./install.sh
```

**macOS** — registers a launchd service that starts on login, restarts on crash, and logs to `~/Library/Logs/desktop-notify-server.log`.

**Linux** — registers a systemd user service that starts on login, restarts on crash, and logs to journald.

### Windows

```powershell
git clone <repo-url>
cd desktop-notifications-from-container
.\install.ps1
```

Registers a Task Scheduler task that starts on login and restarts on failure.

### Uninstall

```bash
# macOS / Linux
./install.sh --uninstall
```

```powershell
# Windows
.\install.ps1 -Uninstall
```

### Manual usage

To run the server directly without installing a service:

```bash
python notify_server.py
```

## API

### `POST /notify`

Send a desktop notification.

**Request body (JSON):**

| Field     | Type   | Required | Default          | Description              |
|-----------|--------|----------|------------------|--------------------------|
| `title`   | string | no       | `"Notification"` | Notification title       |
| `message` | string | no       | `""`             | Notification body text   |
| `sound`   | bool   | no       | `true`           | Play the default sound   |

**Example:**

```bash
curl -X POST http://localhost:6789/notify \
    -H "Content-Type: application/json" \
    -d '{"title":"Build Complete","message":"Your build has finished","sound":true}'
```

**Response:** `200 OK`
```json
{"status": "ok"}
```

### `GET /health`

Health check endpoint.

**Response:** `200 OK`
```json
{"status": "ok"}
```

## Configuration

| Environment variable    | Default | Description                                                         |
|-------------------------|---------|---------------------------------------------------------------------|
| `DESKTOP_NOTIFY_PORT`   | `6789`  | Port to listen on                                                   |
| `ALLOW_SOUND`  | `on`    | Set to `off` to mute all sounds globally, ignoring per-request flag |

To change these for the installed service, edit the values in `install.sh` (or `install.ps1` on Windows) and re-run it.

## Connecting from Docker

The server listens on `127.0.0.1:6789` on the host. There are several ways for a container to reach it.

### Option 1: `host.docker.internal` (recommended for macOS)

Docker Desktop for Mac automatically resolves `host.docker.internal` to the host machine. No extra configuration needed — it works out of the box:

```bash
curl -X POST http://host.docker.internal:6789/notify \
    -H "Content-Type: application/json" \
    -d '{"title":"Task Done","message":"Container finished processing"}'
```

### Option 2: `host-gateway` extra host (Linux / Docker Engine)

On Linux, `host.docker.internal` is not available by default. Add it explicitly with `extra_hosts`:

**docker run:**

```bash
docker run --add-host=host.docker.internal:host-gateway my-image
```

**docker-compose.yml:**

```yaml
services:
  my-app:
    build: .
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Then use `http://host.docker.internal:6789/notify` from inside the container, same as Option 1.

> **Note:** `host-gateway` is a special value that Docker resolves to the host's internal IP. Requires Docker Engine 20.10+.

### Option 3: Host network mode

Run the container directly on the host's network stack. The container can reach the server at `localhost:6789` as if it were a host process:

```bash
docker run --network host my-image
```

```yaml
services:
  my-app:
    build: .
    network_mode: host
```

> **Trade-off:** The container shares the host's network entirely — no port isolation. Not available on Docker Desktop for Mac (only Linux).

### Option 4: Host IP address

Find the host's IP on the Docker bridge network and use it directly:

```bash
# From the host, find the bridge gateway IP
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'
# Typically 172.17.0.1
```

Then from inside the container:

```bash
curl -X POST http://172.17.0.1:6789/notify \
    -H "Content-Type: application/json" \
    -d '{"title":"Done","message":"Finished"}'
```

> **Note:** This requires the server to listen on `0.0.0.0` or the bridge IP instead of `127.0.0.1`. You can bind to all interfaces by modifying the `HTTPServer` bind address in `notify_server.py`, but be aware this exposes the server to the network.

### Verifying connectivity

From inside a running container, check that the server is reachable:

```bash
curl -s http://host.docker.internal:6789/health
# Expected: {"status": "ok"}
```

### Helper function

For convenience, add a shell function to your container's image or entrypoint:

```bash
notify() {
    curl -s -X POST http://host.docker.internal:6789/notify \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"$1\",\"message\":\"$2\"}"
}

# Usage
notify "Build Complete" "All tests passed"
```

## Managing the service

### macOS

```bash
# Stop
launchctl bootout gui/$(id -u)/com.desktop-notify-server

# Start
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.desktop-notify-server.plist

# View logs
tail -f ~/Library/Logs/desktop-notify-server.log
```

### Linux

```bash
# Stop
systemctl --user stop desktop-notify-server

# Start
systemctl --user start desktop-notify-server

# Status
systemctl --user status desktop-notify-server

# View logs
journalctl --user -u desktop-notify-server -f
```

### Windows

```powershell
# Stop
Stop-ScheduledTask -TaskName DesktopNotifyServer

# Start
Start-ScheduledTask -TaskName DesktopNotifyServer

# Status
Get-ScheduledTask -TaskName DesktopNotifyServer
```
