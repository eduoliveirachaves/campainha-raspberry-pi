#!/usr/bin/env python3
"""Fila, persistência SQLite e transporte HTTP da campainha.

A execução do hardware fica em main.py. Este módulo mantém os eventos,
processa uma captura por vez e preserva as fotos ainda não enviadas.
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
