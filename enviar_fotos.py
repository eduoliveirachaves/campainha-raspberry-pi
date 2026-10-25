#!/usr/bin/env python3
"""Facilitador iniciado por run.sh; envia fotos pendentes ao PC pelo túnel SSH."""

import argparse
import fcntl
import json
import logging
from pathlib import Path
import signal
import sqlite3
import threading
import time

import requests

from campainha import Campainha, enviar_http, validar_backend

MAX_TENTATIVAS = 3


def preparar_envios(sistema):
    with sistema.banco() as banco:
        banco.execute("""
            CREATE TABLE IF NOT EXISTS envios_pc (
                id TEXT PRIMARY KEY,
                tentativas INTEGER NOT NULL,
                proxima_tentativa REAL NOT NULL
            )
        """)


def tentar_enviar(sistema, url, token, agora):
    with sistema.banco() as banco:
        linha = banco.execute("""
            SELECT e.*, COALESCE(p.tentativas, 0) AS tentativas
            FROM eventos e LEFT JOIN envios_pc p ON e.id = p.id
            WHERE e.estado = 'capturado' AND e.foto IS NOT NULL AND e.enviado = 0
              AND COALESCE(p.tentativas, 0) < ?
              AND COALESCE(p.proxima_tentativa, 0) <= ?
            ORDER BY COALESCE(p.tentativas, 0), e.rowid LIMIT 1
        """, (MAX_TENTATIVAS, agora)).fetchone()
        if linha is None:
            return False
        registro = dict(linha)
        tentativa = registro["tentativas"] + 1
        # Contar antes da rede preserva o limite mesmo se o processo reiniciar.
        banco.execute("""
            INSERT INTO envios_pc (id, tentativas, proxima_tentativa) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET tentativas = excluded.tentativas,
                                         proxima_tentativa = excluded.proxima_tentativa
        """, (registro["id"], tentativa, agora + 5))
    arquivo = Path(registro["foto"])
    logging.info("Enviando %s — tentativa %d/%d", arquivo.name, tentativa, MAX_TENTATIVAS)
    try:
        enviar_http(url, token, registro, arquivo)
    except (requests.RequestException, OSError, ValueError) as erro:
        logging.warning("Falha: %s — tentativa %d/%d: %s", arquivo.name, tentativa, MAX_TENTATIVAS, erro)
        if tentativa == MAX_TENTATIVAS:
            logging.error("Limite de %d tentativas: %s — envio encerrado; arquivo preservado no Raspberry", MAX_TENTATIVAS, arquivo.name)
    else:
        with sistema.banco() as banco:
            banco.execute("UPDATE eventos SET enviado = 1 WHERE id = ?", (registro["id"],))
        logging.info("Enviado: %s — tentativa %d/%d", arquivo.name, tentativa, MAX_TENTATIVAS)
    return True


def main():
    raiz = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pasta", type=Path, default=raiz / "fotos")
    parser.add_argument("--verificar", action="store_true")
    args = parser.parse_args()
    config = json.loads((raiz / "pc.json").read_text())
    url, token = config["url"], config["token"]
    validar_backend(url, token)
    if args.verificar:
        try:
            resposta = requests.get(url.rsplit("/", 1)[0] + "/health",
                                    headers={"Authorization": "Bearer " + token}, timeout=2)
            resposta.raise_for_status()
        except requests.RequestException:
            raise SystemExit("Recebimento do PC indisponível. No computador: bash scripts/preparar_recebimento.sh (ou edu pi, se configurado).") from None
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s ENVIO %(message)s", datefmt="%H:%M:%S")
    parar = threading.Event()
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, lambda *_: parar.set())
    sistema = Campainha(args.pasta, capturar=None)
    with (sistema.pasta / "envio.lock").open("a") as bloqueio:
        try:
            fcntl.flock(bloqueio, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("O envio automático já está em execução") from None
        preparar_envios(sistema)
        logging.info("Envio automático iniciado; máximo de %d tentativas por foto", MAX_TENTATIVAS)
        while not parar.is_set():
            try:
                if not tentar_enviar(sistema, url, token, time.time()):
                    parar.wait(0.5)
            except sqlite3.Error:
                logging.exception("Falha ao acessar a fila de envios")
                parar.wait(1)


if __name__ == "__main__":
    main()
