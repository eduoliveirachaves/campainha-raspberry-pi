#!/usr/bin/env python3
"""Campainha: botão BCM17, buzzer BCM18 e câmera CSI.

Execução: python3 main.py (Raspberry Pi OS com GPIO Zero e rpicam-apps).
"""

import contextlib
import logging
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4


class Campainha:
    def __init__(self, pasta, capturar, relogio=time.monotonic, max_fotos=200):
        if max_fotos < 1:
            raise ValueError("O limite de fotos precisa ser positivo")
        self.pasta = Path(pasta).expanduser().resolve()
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.capturar = capturar
        self.relogio = relogio
        self.max_fotos = max_fotos
        self.ultimo_movimento = None
        self.trava = threading.Lock()
        with self.banco() as banco:
            banco.execute("""
                CREATE TABLE IF NOT EXISTS eventos (
                    id TEXT PRIMARY KEY,
                    origem TEXT NOT NULL,
                    criado_em TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'aguardando',
                    foto TEXT,
                    erro TEXT NOT NULL DEFAULT '',
                    enviado INTEGER NOT NULL DEFAULT 0
                )
            """)

    @contextlib.contextmanager
    def banco(self):
        # Cada thread usa sua conexão; nenhuma espera de rede mantém o banco aberto.
        conexao = sqlite3.connect(self.pasta / "eventos.sqlite3", timeout=5)
        conexao.row_factory = sqlite3.Row
        try:
            with conexao:
                yield conexao
        finally:
            conexao.close()

    def registrar(self, origem):
        if origem not in ("botao", "movimento"):
            raise ValueError("Origem inválida")
        with self.trava:
            agora = self.relogio()
            if origem == "movimento" and self.ultimo_movimento is not None:
                if agora - self.ultimo_movimento < 30:
                    return None
            identificador = str(uuid4())
            with self.banco() as banco:
                banco.execute(
                    "INSERT INTO eventos (id, origem, criado_em) VALUES (?, ?, ?)",
                    (identificador, origem, datetime.now(timezone.utc).isoformat()),
                )
            if origem == "movimento":
                self.ultimo_movimento = agora
        return identificador

    def evento(self, identificador):
        with self.banco() as banco:
            linha = banco.execute(
                "SELECT * FROM eventos WHERE id = ?", (identificador,)
            ).fetchone()
            return dict(linha) if linha else None

    def liberar_espaco(self):
        # Nunca apagar fotos pendentes de envio para abrir espaço a novas visitas.
        with self.banco() as banco:
            while len(list(self.pasta.glob("*.jpg"))) >= self.max_fotos:
                antigo = banco.execute("""
                    SELECT id, foto FROM eventos
                    WHERE enviado = 1 AND foto IS NOT NULL ORDER BY rowid LIMIT 1
                """).fetchone()
                if antigo is None:
                    raise RuntimeError("Limite de fotos: há imagens sem envio")
                Path(antigo["foto"]).unlink(missing_ok=True)
                banco.execute("UPDATE eventos SET foto = NULL WHERE id = ?",
                              (antigo["id"],))
        if shutil.disk_usage(self.pasta).free < 10 * 1024 * 1024:
            raise RuntimeError("Espaço livre insuficiente para uma nova foto")

    def processar(self):
        # Só a thread de captura chama este método; processar um evento por vez.
        with self.banco() as banco:
            linha = banco.execute("""
                SELECT * FROM eventos WHERE estado = 'aguardando'
                ORDER BY CASE origem WHEN 'botao' THEN 0 ELSE 1 END, rowid LIMIT 1
            """).fetchone()
        if linha is None:
            return False
        arquivo = self.pasta / datetime.now().strftime("%H-%M-%S__%d-%m.jpg")
        # Capturas no mesmo segundo nunca sobrescrevem uma foto já salva.
        while arquivo.exists():
            time.sleep(0.05)
            arquivo = self.pasta / datetime.now().strftime("%H-%M-%S__%d-%m.jpg")
        logging.info("Iniciando captura: %s (%s)", arquivo.name, linha["origem"])
        erro = ""
        try:
            self.liberar_espaco()
            self.capturar(arquivo)
            if not arquivo.is_file() or arquivo.stat().st_size == 0:
                raise RuntimeError("A câmera não produziu uma imagem")
        except (OSError, RuntimeError) as falha:
            arquivo.unlink(missing_ok=True)
            erro = str(falha)
            logging.warning("Falha de captura para %s: %s", arquivo.name, erro)
        with self.banco() as banco:
            banco.execute(
                "UPDATE eventos SET estado = ?, foto = ?, erro = ? WHERE id = ?",
                ("erro" if erro else "capturado", None if erro else str(arquivo),
                 erro, linha["id"]),
            )
        return True

    def enviar(self, transmitir):
        with self.banco() as banco:
            linha = banco.execute("""
                SELECT * FROM eventos WHERE estado != 'aguardando' AND enviado = 0
                ORDER BY rowid LIMIT 1
            """).fetchone()
        if linha is None:
            return False
        registro = dict(linha)
        transmitir(registro, Path(registro["foto"]) if registro["foto"] else None)
        # Se transmitir falhar, o registro continua pendente e conserva seu id.
        with self.banco() as banco:
            banco.execute("UPDATE eventos SET enviado = 1 WHERE id = ?",
                          (registro["id"],))
        logging.info("Evento enviado: %s", Path(registro["foto"]).name if registro["foto"] else "evento sem foto")
        return True


def validar_backend(url, token):
    destino = urlsplit(url)
    local = destino.hostname in ("localhost", "127.0.0.1", "::1")
    if (destino.scheme not in ("http", "https") or not destino.hostname
            or destino.username or destino.password or destino.fragment
            or (destino.scheme == "http" and not local)):
        raise ValueError("Use HTTPS; HTTP é permitido apenas no próprio computador")
    if not token.strip():
        raise ValueError("Configure BACKEND_TOKEN para enviar os registros")


def enviar_http(url, token, registro, foto):
    import requests

    arquivos = {chave: (None, registro[chave])
                for chave in ("id", "origem", "criado_em", "erro")}
    with contextlib.ExitStack() as recursos:
        if foto:
            imagem = recursos.enter_context(foto.open("rb"))
            arquivos["foto"] = (foto.name, imagem, "image/jpeg")
        resposta = requests.post(
            url, files=arquivos,
            headers={"Authorization": "Bearer " + token},
            timeout=(5, 15), allow_redirects=False,
        )
    resposta.raise_for_status()
    if not 200 <= resposta.status_code < 300:
        raise ValueError("O backend não confirmou o recebimento")
    confirmacao = resposta.json()
    if not isinstance(confirmacao, dict) or confirmacao.get("id") != registro["id"]:
        raise ValueError("O backend não confirmou o identificador do evento")


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
