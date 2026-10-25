#!/usr/bin/env bash
set -euo pipefail
ip=${1:-}
if [[ -z "$ip" ]]; then
    ip=$(getent ahostsv4 raspberrypi.local | awk 'NR == 1 { print $1 }')
    if [[ -z "$ip" ]] || ! ping -n -c 1 -W 2 "$ip" >/dev/null 2>&1; then
        printf 'Raspberry não respondeu em até dois segundos; confira a rede e raspberrypi.local.\n' >&2
        exit 1
    fi
fi
raiz=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
runtime="/tmp/edu-raspberry-$UID"
umask 077
mkdir -p "$runtime"
config="$runtime/pc.json"
if [[ ! -s "$config" ]]; then
    /usr/bin/python3 - "$config" <<'PY'
import json
from pathlib import Path
import secrets
import sys
Path(sys.argv[1]).write_text(json.dumps({
    "url": "http://127.0.0.1:8766/eventos", "token": secrets.token_urlsafe(32),
}))
PY
fi
if ! /usr/bin/python3 "$raiz/receber_fotos.py" --config "$config" --check; then
    setsid -f /usr/bin/python3 -u "$raiz/receber_fotos.py" --config "$config" \
        > "$runtime/receptor.log" 2>&1 < /dev/null
    for tentativa in {1..10}; do
        if /usr/bin/python3 "$raiz/receber_fotos.py" --config "$config" --check; then
            break
        fi
        sleep 0.2
    done
    /usr/bin/python3 "$raiz/receber_fotos.py" --config "$config" --check || {
        printf 'Erro ao iniciar receptor; consulte %s/receptor.log\n' "$runtime" >&2
        exit 1
    }
fi
opcoes=(-i "$HOME/.ssh/id_ed25519_rasp" -o IdentitiesOnly=yes -o ForwardAgent=no
        -o BatchMode=yes -o ConnectTimeout=5 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
if ! ssh -S "$runtime/tunnel" -O check "admin@$ip" >/dev/null 2>&1; then
    setsid -w ssh "${opcoes[@]}" -fN -M -S "$runtime/tunnel" \
        -o ExitOnForwardFailure=yes -R 127.0.0.1:8766:127.0.0.1:8766 "admin@$ip"
fi
setsid -w scp "${opcoes[@]}" -o ControlPath="$runtime/tunnel" \
    "$config" "admin@$ip:projeto/pc.json" >/dev/null
ssh "${opcoes[@]}" -S "$runtime/tunnel" "admin@$ip" 'chmod 600 ~/projeto/pc.json'
printf 'Recebimento automático pronto: ~/Pictures/embarcados/\n'
