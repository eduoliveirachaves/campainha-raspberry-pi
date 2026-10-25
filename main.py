#!/usr/bin/env python3
"""Campainha da montagem atual: botão BCM17, buzzer BCM18 e câmera CSI."""

import argparse
import contextlib
import fcntl
import logging
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import threading

from campainha import Campainha


def main():
    raiz = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pasta", type=Path, default=raiz / "fotos")
    args = parser.parse_args()
    camera = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    if camera is None:
        raise RuntimeError("Não encontrei rpicam-still/libcamera-still")

    from gpiozero import Button, PWMOutputDevice

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    parar = threading.Event()
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, lambda *_: parar.set())

    with contextlib.ExitStack() as recursos:
        args.pasta.mkdir(parents=True, exist_ok=True)
        bloqueio = recursos.enter_context((args.pasta / "execucao.lock").open("a"))
        try:
            fcntl.flock(bloqueio, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A campainha já está em execução") from None
        botao = recursos.enter_context(Button(17, pull_up=True, bounce_time=0.05))
        buzzer = recursos.enter_context(PWMOutputDevice(18, frequency=2000, initial_value=0))

        def capturar(arquivo):
            buzzer.value = 0.5
            parar.wait(0.2)
            buzzer.off()
            try:
                subprocess.run(
                    [camera, "--nopreview", "--timeout", "1000", "--output", str(arquivo)],
                    check=True, timeout=30, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as erro:
                raise RuntimeError(erro.stderr[-2000:]) from erro
            except subprocess.TimeoutExpired as erro:
                raise RuntimeError("A câmera excedeu 30 segundos") from erro
            logging.info("Foto capturada: %s", arquivo.name)

        sistema = Campainha(args.pasta, capturar)

        def registrar():
            try:
                sistema.registrar("botao")
            except (OSError, sqlite3.Error):
                logging.exception("Não foi possível registrar o botão")

        def capturas():
            while not parar.is_set():
                try:
                    if not sistema.processar():
                        parar.wait(0.1)
                except (OSError, RuntimeError, sqlite3.Error):
                    logging.exception("Falha no processamento da foto")
                    parar.wait(1)

        trabalhadores = [threading.Thread(target=capturas)]
        for trabalhador in trabalhadores:
            trabalhador.start()
        botao.when_pressed = registrar
        logging.info("PRONTO: aperte o botão no GPIO17. Ctrl+C para encerrar.")
        try:
            parar.wait()
        finally:
            botao.when_pressed = None
            parar.set()
            for trabalhador in trabalhadores:
                trabalhador.join()


if __name__ == "__main__":
    main()
