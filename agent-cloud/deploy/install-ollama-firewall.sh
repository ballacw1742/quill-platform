#!/bin/bash
# Install a persistent pf rule restricting ollama :11434 to loopback + tailnet.
# Idempotent: safe to re-run. Preserves the stock /etc/pf.conf (only appends
# our anchor if not already present) and installs a LaunchDaemon so pf + our
# rules load at every boot (macOS does NOT enable pf automatically).
set -euo pipefail

SRC_ANCHOR="/Users/charlesmitchell/.openclaw/workspace/quill-platform/agent-cloud/deploy/ollama-tailnet-only.pf.conf"
ANCHOR_DST="/etc/pf.anchors/ollama-tailnet-only"
PF_CONF="/etc/pf.conf"
PLIST="/Library/LaunchDaemons/com.charles.ollama-firewall.plist"

echo "== 1. install anchor file =="
cp "$SRC_ANCHOR" "$ANCHOR_DST"
chown root:wheel "$ANCHOR_DST"
chmod 644 "$ANCHOR_DST"

echo "== 2. reference anchor from /etc/pf.conf (preserve existing, append once) =="
if ! grep -q 'ollama-tailnet-only' "$PF_CONF"; then
  cp "$PF_CONF" "${PF_CONF}.bak-ollama-$(date +%Y%m%d)"
  {
    echo ''
    echo '# ollama tailnet-only restriction (§8 model-lane router)'
    echo 'anchor "ollama-tailnet-only"'
    echo 'load anchor "ollama-tailnet-only" from "/etc/pf.anchors/ollama-tailnet-only"'
  } >> "$PF_CONF"
  echo "   appended anchor refs (backup at ${PF_CONF}.bak-ollama-*)"
else
  echo "   already referenced — skipping"
fi

echo "== 3. validate + (re)load pf =="
pfctl -n -f "$PF_CONF"          # dry-run parse; fails the script if invalid
pfctl -E -f "$PF_CONF" 2>&1 | tail -3 || true   # enable + load

echo "== 4. install LaunchDaemon so pf loads our rules at boot =="
cat > "$PLIST" <<'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.charles.ollama-firewall</string>
  <key>ProgramArguments</key>
  <array>
    <string>/sbin/pfctl</string>
    <string>-E</string>
    <string>-f</string>
    <string>/etc/pf.conf</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>/var/log/ollama-firewall.log</string>
  <key>StandardOutPath</key><string>/var/log/ollama-firewall.log</string>
</dict>
</plist>
PLIST_EOF
chown root:wheel "$PLIST"
chmod 644 "$PLIST"
launchctl bootout system "$PLIST" 2>/dev/null || true
launchctl bootstrap system "$PLIST" 2>&1 || true

echo "== 5. verify anchor is loaded =="
pfctl -a 'ollama-tailnet-only' -s rules 2>&1 || true
echo "DONE"
