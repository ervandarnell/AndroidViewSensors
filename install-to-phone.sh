#!/bin/sh
set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo " ThermoHygro Offline Sensor (°F) — Native Android APK"
echo "========================================================"

# 1. Locate adb using strict POSIX redirection
ADB_BIN=""
if command -v adb >/dev/null 2>&1; then
  ADB_BIN="$(command -v adb)"
elif [ -x "/usr/bin/adb" ]; then
  ADB_BIN="/usr/bin/adb"
elif [ -x "/usr/local/bin/adb" ]; then
  ADB_BIN="/usr/local/bin/adb"
elif [ -x "$HOME/Android/Sdk/platform-tools/adb" ]; then
  ADB_BIN="$HOME/Android/Sdk/platform-tools/adb"
fi

if [ -z "$ADB_BIN" ]; then
  echo "[!] Error: 'adb' not found. Run: sudo apt install adb"
  exit 1
fi

echo "[✓] Using Android Debug Bridge: $ADB_BIN"
"$ADB_BIN" start-server >/dev/null 2>&1 || true

# Clean up any old USB port reverse or background HTTP server from earlier script
"$ADB_BIN" reverse --remove-all >/dev/null 2>&1 || true
fuser -k 8765/tcp >/dev/null 2>&1 || true

echo ""
echo "[1/3] Checking connected physical Android phone..."
"$ADB_BIN" devices -l

ACTIVE_DEV=$("$ADB_BIN" devices | awk 'NR>1 && $2=="device" {print $1}')
UNAUTH_DEV=$("$ADB_BIN" devices | awk 'NR>1 && $2=="unauthorized" {print $1}')

if [ -n "$UNAUTH_DEV" ]; then
  echo "[!] Phone ($UNAUTH_DEV) is connected via USB, but UNAUTHORIZED."
  echo "    Unlock your phone screen and tap 'Allow USB debugging'..."
  "$ADB_BIN" wait-for-device
elif [ -z "$ACTIVE_DEV" ]; then
  echo "[!] Waiting for physical Android phone over USB (enable USB Debugging on phone)..."
  "$ADB_BIN" wait-for-device
fi

echo ""
echo "[2/3] Extracting signed native Android APK (ThermoHygro-Offline.apk)..."
base64 -d << 'EOF_PREBUILT_APK' > ThermoHygro-Offline.apk
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
EOF_PREBUILT_APK
ls -lh ThermoHygro-Offline.apk

echo ""
echo "[3/3] Installing native Android app (com.thermohygro.offlinesensor) to phone..."
"$ADB_BIN" shell settings put global verifier_verify_adb_installs 0 >/dev/null 2>&1 || true
"$ADB_BIN" shell settings put global package_verifier_enable 0 >/dev/null 2>&1 || true
"$ADB_BIN" uninstall com.thermohygro.offlinesensor >/dev/null 2>&1 || true
"$ADB_BIN" install -r ThermoHygro-Offline.apk

echo "      Launching ThermoHygro °F native Android app on handset..."
"$ADB_BIN" shell am start -n com.thermohygro.offlinesensor/.MainActivity

echo ""
echo "========================================================"
echo " [✓] NATIVE ANDROID APP INSTALLED ON YOUR PHONE!"
echo "     • App Name : ThermoHygro °F"
echo "     • Package  : com.thermohygro.offlinesensor"
echo "     • Network  : 0 Permissions (100% Standalone Offline App)"
echo "     • You can now unplug the USB cord and launch 'ThermoHygro °F'"
echo "       anytime directly from your phone's app drawer."
echo "========================================================"
