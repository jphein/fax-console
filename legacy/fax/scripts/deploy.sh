#!/usr/bin/env bash
# deploy.sh — install the fax CLI on pbx so the Telephony Console can call it.
#   /usr/local/lib/fax/cli.py   (the code)
#   /usr/local/bin/fax          (wrapper)
# Also makes sure ghostscript is present (needed for PDF → TIFF on the box).
set -euo pipefail
export SSH_ASKPASS_REQUIRE=never; unset DISPLAY
HOST=${1:-pbx}
HERE=$(cd "$(dirname "$0")/.." && pwd)
python3 -m py_compile "$HERE/fax/cli.py"
scp -q -o BatchMode=yes "$HERE/fax/cli.py" "$HOST:/tmp/fax-cli.py"
ssh -o BatchMode=yes "$HOST" '
  set -e
  sudo install -d -o root -g root -m 755 /usr/local/lib/fax
  sudo install -o root -g root -m 644 /tmp/fax-cli.py /usr/local/lib/fax/cli.py && rm -f /tmp/fax-cli.py
  printf "%s\n" "#!/usr/bin/env bash" "exec python3 /usr/local/lib/fax/cli.py --local \"\$@\"" | sudo tee /usr/local/bin/fax >/dev/null
  sudo chmod 755 /usr/local/bin/fax
  command -v gs >/dev/null || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q ghostscript
  # Ubuntu ships an AppArmor profile for gs that denies reading anything outside a short list
  # (measured 2026-09-26: "apparmor=DENIED ... profile=gs name=/tmp/p.pdf"). Let it read the
  # console's uploads and write the fax spool; the profile includes local/gs.
  if [ -f /etc/apparmor.d/gs ] && ! grep -q telephony-console/fax /etc/apparmor.d/local/gs 2>/dev/null; then
    printf "%s\n" "# fax: ghostscript may read console uploads and write fax TIFFs (~/Projects/fax deploy.sh)" \
      "/var/lib/telephony-console/fax/** r," "/var/spool/asterisk/fax/** rw," "/tmp/** rw," | sudo tee -a /etc/apparmor.d/local/gs >/dev/null
    sudo apparmor_parser -r /etc/apparmor.d/gs
  fi
  sudo install -d -o asterisk -g asterisk -m 775 /var/spool/asterisk/fax
  fax status'
