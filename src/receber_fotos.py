#!/usr/bin/env python3
"""Recebe fotos apenas no localhost; o Raspberry acessa pelo túnel SSH."""

import argparse
from email import policy
from email.parser import BytesParser
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
import tempfile
from urllib.request import Request, urlopen
from uuid import UUID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    token = config["token"]
    if args.check:
        pedido = Request("http://127.0.0.1:8766/health", headers={"Authorization": "Bearer " + token})
        try:
            with urlopen(pedido, timeout=2) as resposta:
                return 0 if resposta.status == 200 else 1
        except OSError:
            return 1
    destino = Path.home() / "Pictures/embarcados"
    destino.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    class Receptor(BaseHTTPRequestHandler):
        def autorizado(self):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            if self.path != "/health" or not self.autorizado():
                self.send_error(403)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            if self.path != "/eventos" or not self.autorizado():
                self.send_error(403)
                return
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
                if not 0 < tamanho <= 20 * 1024 * 1024:
                    self.send_error(413)
                    return
                self.connection.settimeout(20)
                corpo = self.rfile.read(tamanho)
                if len(corpo) != tamanho:
                    raise ValueError("Envio incompleto")
                mensagem = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + self.headers.get("Content-Type", "").encode("ascii")
                    + b"\r\nMIME-Version: 1.0\r\n\r\n" + corpo)
                partes = {parte.get_param("name", header="content-disposition"):
                          parte for parte in mensagem.iter_parts()}
                campos = {nome: parte.get_payload(decode=True) for nome, parte in partes.items()}
                identificador = str(UUID(campos["id"].decode("ascii")))
                foto = campos.get("foto")
                if foto is not None:
                    nome = partes["foto"].get_filename()
                    if not re.fullmatch(r"[0-9]{2}-[0-9]{2}-[0-9]{2}__[0-9]{2}-[0-9]{2}\.jpg", nome or ""):
                        # Compatibilidade com fotos pendentes da execução anterior.
                        if nome != identificador + ".jpg":
                            raise ValueError("Nome de foto inválido")
                    if not foto.startswith(b"\xff\xd8"):
                        raise ValueError("Foto JPEG inválida")
                    alvo = destino / nome
                    if alvo.exists() and alvo.read_bytes() != foto:
                        logging.error("Conflito de nome; arquivo existente preservado: %s", nome)
                        self.send_error(409)
                        return
                    with tempfile.NamedTemporaryFile(dir=destino, delete=False, suffix=".part") as arquivo:
                        temporario = Path(arquivo.name)
                        try:
                            arquivo.write(foto)
                            arquivo.flush()
                            temporario.replace(alvo)
                        finally:
                            temporario.unlink(missing_ok=True)
                    logging.info("Foto recebida: %s", alvo)
                else:
                    logging.warning("Evento sem foto: %s (%s)", identificador, campos.get("erro", b"").decode(errors="replace"))
                resposta = json.dumps({"id": identificador}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resposta)))
                self.end_headers()
                self.wfile.write(resposta)
            except (ValueError, KeyError, UnicodeError):
                self.send_error(400)
            except OSError:
                logging.exception("Falha ao salvar foto")
                self.send_error(500)

        def log_message(self, *args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 8766), Receptor)
    logging.info("Aguardando fotos pelo túnel SSH; destino: %s", destino)
    servidor.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
