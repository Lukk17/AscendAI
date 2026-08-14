#!/bin/sh
set -eu

VNC_PASSWORD_FILE=/run/vnc/passwd

if [ -n "${VNC_PASSWORD:-}" ]; then
    mkdir -p "$(dirname "${VNC_PASSWORD_FILE}")"
    x11vnc -storepasswd "${VNC_PASSWORD}" "${VNC_PASSWORD_FILE}" >/dev/null 2>&1
    chmod 600 "${VNC_PASSWORD_FILE}"
    X11VNC_AUTH_FLAG="-rfbauth ${VNC_PASSWORD_FILE}"
    echo "[AscendSearch] VNC authentication enabled. The VNC protocol truncates passwords to 8 characters."
else
    X11VNC_AUTH_FLAG="-nopw"
    echo "[AscendSearch] WARNING: VNC_PASSWORD is unset. The NoVNC desktop on port 7900 accepts any client without authentication. Do not publish or tunnel port 7900 while it is in this state."
fi

export X11VNC_AUTH_FLAG

exec "$@"
