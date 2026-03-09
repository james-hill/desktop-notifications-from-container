#!/bin/bash
set -euo pipefail

SERVICE_NAME="desktop-notify-server"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OS="$(uname -s)"

# Resolve the real python path (follow symlinks/shims)
find_python() {
    local py
    py="$(command -v python3 2>/dev/null || true)"
    if [[ -z "$py" ]]; then
        echo "Error: python3 not found. Install Python 3.10+ and try again." >&2
        exit 1
    fi
    "$py" -c 'import sys; print(sys.executable)'
}

# ── macOS (launchd) ──────────────────────────────────────────────────────────

MACOS_LABEL="com.desktop-notify-server"
MACOS_PLIST_NAME="${MACOS_LABEL}.plist"

install_macos() {
    local python_real launch_dir log_dir wrapper_bin
    python_real="$(find_python)"
    launch_dir="$HOME/Library/LaunchAgents"
    log_dir="$HOME/Library/Logs"
    wrapper_bin="$SCRIPT_DIR/$SERVICE_NAME"

    echo "Installing $SERVICE_NAME (launchd)..."
    echo "  Python:  $python_real"
    echo "  Script:  $SCRIPT_DIR/notify_server.py"
    echo "  Logs:    $log_dir/$SERVICE_NAME.log"

    if launchctl list "$MACOS_LABEL" &>/dev/null; then
        echo "  Stopping existing service..."
        launchctl bootout "gui/$(id -u)/$MACOS_LABEL" 2>/dev/null || true
    fi

    mkdir -p "$launch_dir" "$log_dir"

    # Create a named wrapper script so macOS shows "desktop-notify-server"
    # instead of "Python 3" in Background Items / Login Items.
    cat > "$wrapper_bin" <<WRAPPER
#!${python_real}
import runpy, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
runpy.run_module("notify_server", run_name="__main__", alter_sys=True)
WRAPPER
    chmod +x "$wrapper_bin"

    cat > "$launch_dir/$MACOS_PLIST_NAME" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${MACOS_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${wrapper_bin}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${log_dir}/${SERVICE_NAME}.log</string>

    <key>StandardErrorPath</key>
    <string>${log_dir}/${SERVICE_NAME}.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>DESKTOP_NOTIFY_PORT</key>
        <string>6789</string>
        <key>ALLOW_SOUND</key>
        <string>on</string>
    </dict>
</dict>
</plist>
EOF

    launchctl bootstrap "gui/$(id -u)" "$launch_dir/$MACOS_PLIST_NAME"

    echo "Done! Service is running."
    echo ""
    echo "Manage with:"
    echo "  Stop:    launchctl bootout gui/\$(id -u)/$MACOS_LABEL"
    echo "  Start:   launchctl bootstrap gui/\$(id -u) $launch_dir/$MACOS_PLIST_NAME"
    echo "  Logs:    tail -f $log_dir/$SERVICE_NAME.log"
    echo "  Remove:  $0 --uninstall"
}

uninstall_macos() {
    local launch_dir="$HOME/Library/LaunchAgents"
    local wrapper_bin="$SCRIPT_DIR/$SERVICE_NAME"
    echo "Uninstalling $SERVICE_NAME (launchd)..."
    if launchctl list "$MACOS_LABEL" &>/dev/null; then
        launchctl bootout "gui/$(id -u)/$MACOS_LABEL" 2>/dev/null || true
        echo "  Service stopped."
    fi
    if [[ -f "$launch_dir/$MACOS_PLIST_NAME" ]]; then
        rm "$launch_dir/$MACOS_PLIST_NAME"
        echo "  Plist removed."
    fi
    if [[ -f "$wrapper_bin" ]]; then
        rm "$wrapper_bin"
        echo "  Wrapper script removed."
    fi
    echo "Done."
}

# ── Linux (systemd) ─────────────────────────────────────────────────────────

SYSTEMD_UNIT="$SERVICE_NAME.service"

install_linux() {
    local python_real unit_dir log_dir
    python_real="$(find_python)"
    unit_dir="$HOME/.config/systemd/user"

    echo "Installing $SERVICE_NAME (systemd)..."
    echo "  Python:  $python_real"
    echo "  Script:  $SCRIPT_DIR/notify_server.py"

    mkdir -p "$unit_dir"

    cat > "$unit_dir/$SYSTEMD_UNIT" <<EOF
[Unit]
Description=Desktop Notify Server
After=network.target

[Service]
Type=simple
ExecStart=${python_real} ${SCRIPT_DIR}/notify_server.py
Restart=always
RestartSec=3
Environment=DESKTOP_NOTIFY_PORT=6789
Environment=ALLOW_SOUND=on

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now "$SYSTEMD_UNIT"

    echo "Done! Service is running."
    echo ""
    echo "Manage with:"
    echo "  Status:  systemctl --user status $SYSTEMD_UNIT"
    echo "  Stop:    systemctl --user stop $SYSTEMD_UNIT"
    echo "  Start:   systemctl --user start $SYSTEMD_UNIT"
    echo "  Logs:    journalctl --user -u $SYSTEMD_UNIT -f"
    echo "  Remove:  $0 --uninstall"
}

uninstall_linux() {
    local unit_dir="$HOME/.config/systemd/user"
    echo "Uninstalling $SERVICE_NAME (systemd)..."
    if systemctl --user is-active "$SYSTEMD_UNIT" &>/dev/null; then
        systemctl --user stop "$SYSTEMD_UNIT"
        echo "  Service stopped."
    fi
    if systemctl --user is-enabled "$SYSTEMD_UNIT" &>/dev/null; then
        systemctl --user disable "$SYSTEMD_UNIT"
    fi
    if [[ -f "$unit_dir/$SYSTEMD_UNIT" ]]; then
        rm "$unit_dir/$SYSTEMD_UNIT"
        systemctl --user daemon-reload
        echo "  Unit file removed."
    fi
    echo "Done."
}

# ── Dispatch ─────────────────────────────────────────────────────────────────

case "$OS" in
    Darwin)
        if [[ "${1:-}" == "--uninstall" ]]; then
            uninstall_macos
        else
            install_macos
        fi
        ;;
    Linux)
        if [[ "${1:-}" == "--uninstall" ]]; then
            uninstall_linux
        else
            install_linux
        fi
        ;;
    *)
        echo "Error: Unsupported OS ($OS). See install.ps1 for Windows." >&2
        exit 1
        ;;
esac
