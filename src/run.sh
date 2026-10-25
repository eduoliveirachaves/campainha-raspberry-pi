#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -f pc.json ]]; then
    printf 'No computador, execute bash src/preparar_recebimento.sh, na raiz do projeto (ou edu pi, se configurado).\n' >&2
    exit 1
fi
/usr/bin/python3 enviar_fotos.py --verificar "$@"
envio_pid=''
main_pid=''
encerrar() {
    trap - EXIT INT TERM
    [[ -z "$main_pid" ]] || kill -TERM "$main_pid" 2>/dev/null || true
    [[ -z "$envio_pid" ]] || kill -TERM "$envio_pid" 2>/dev/null || true
    [[ -z "$main_pid" ]] || wait "$main_pid" 2>/dev/null || true
    [[ -z "$envio_pid" ]] || wait "$envio_pid" 2>/dev/null || true
}
trap encerrar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
/usr/bin/python3 -u enviar_fotos.py "$@" &
envio_pid=$!
/usr/bin/python3 -u main.py "$@" &
main_pid=$!
wait -n "$main_pid" "$envio_pid"
