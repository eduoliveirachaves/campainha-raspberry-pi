import tempfile
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from campainha import Campainha, enviar_http, validar_backend


class TestCampainha(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        self.instante = 100.0
        self.sistema = Campainha(
            self.pasta,
            lambda arquivo: arquivo.write_bytes(b"foto de teste"),
            relogio=lambda: self.instante,
            max_fotos=1,
        )

    def test_botao_tem_prioridade_sem_descartar_o_movimento(self):
        movimento = self.sistema.registrar("movimento")
        botao = self.sistema.registrar("botao")
        self.sistema.processar()
        self.assertEqual(self.sistema.evento(botao)["estado"], "capturado")
        self.assertEqual(self.sistema.evento(movimento)["estado"], "aguardando")

    def test_intervalo_do_pir_nao_bloqueia_botao(self):
        self.assertIsNotNone(self.sistema.registrar("movimento"))
        self.instante = 101
        self.assertIsNone(self.sistema.registrar("movimento"))
        self.assertIsNotNone(self.sistema.registrar("botao"))
        self.instante = 130
        self.assertIsNotNone(self.sistema.registrar("movimento"))

    def test_toque_durante_captura_fica_para_a_proxima_captura(self):
        novos = []

        def capturar(arquivo):
            novos.append(self.sistema.registrar("botao"))
            arquivo.write_bytes(b"foto de teste")

        self.sistema.capturar = capturar
        primeiro = self.sistema.registrar("botao")
        self.sistema.processar()
        self.assertEqual(self.sistema.evento(primeiro)["estado"], "capturado")
        self.assertEqual(self.sistema.evento(novos[0])["estado"], "aguardando")

    def test_falha_da_camera_preserva_evento_sem_foto_parcial(self):
        def falhar(arquivo):
            arquivo.write_bytes(b"incompleta")
            raise RuntimeError("camera desconectada")

        self.sistema.capturar = falhar
        evento = self.sistema.registrar("botao")
        self.sistema.processar()
        salvo = self.sistema.evento(evento)
        self.assertEqual(salvo["estado"], "erro")
        self.assertIn("camera desconectada", salvo["erro"])
        self.assertIsNone(salvo["foto"])
        self.assertEqual(list(self.pasta.glob("*.jpg")), [])

    def test_eventos_sobrevivem_ao_reinicio(self):
        evento = self.sistema.registrar("botao")
        reiniciado = Campainha(self.pasta, self.sistema.capturar)
        reiniciado.processar()
        self.assertEqual(reiniciado.evento(evento)["estado"], "capturado")

    def test_falha_no_envio_mantem_evento_pendente(self):
        evento = self.sistema.registrar("botao")
        self.sistema.processar()

        def falhar(registro, foto):
            raise OSError("sem rede")

        with self.assertRaises(OSError):
            self.sistema.enviar(falhar)
        self.assertEqual(self.sistema.evento(evento)["enviado"], 0)
        recebidos = []
        self.sistema.enviar(lambda registro, foto: recebidos.append(registro))
        self.assertEqual(recebidos[0]["id"], evento)
        self.assertEqual(self.sistema.evento(evento)["enviado"], 1)
        self.assertFalse(self.sistema.enviar(falhar))

    def test_limite_de_fotos_nao_apaga_imagem_ainda_nao_enviada(self):
        primeiro = self.sistema.registrar("botao")
        self.sistema.processar()
        foto = Path(self.sistema.evento(primeiro)["foto"])
        segundo = self.sistema.registrar("botao")
        self.sistema.processar()
        self.assertTrue(foto.exists())
        self.assertEqual(self.sistema.evento(segundo)["estado"], "erro")
        self.assertIn("Limite de fotos", self.sistema.evento(segundo)["erro"])

    def test_retencao_remove_so_foto_enviada_e_preserva_historico(self):
        primeiro = self.sistema.registrar("botao")
        self.sistema.processar()
        foto = Path(self.sistema.evento(primeiro)["foto"])
        self.sistema.enviar(lambda registro, arquivo: None)
        segundo = self.sistema.registrar("botao")
        self.sistema.processar()
        self.assertFalse(foto.exists())
        self.assertIsNone(self.sistema.evento(primeiro)["foto"])
        self.assertEqual(self.sistema.evento(primeiro)["enviado"], 1)
        self.assertEqual(self.sistema.evento(segundo)["estado"], "capturado")

    def test_backend_exige_destino_valido_e_token(self):
        for url in ["file:///tmp/foto", "http://servidor.exemplo/eventos",
                    "https://usuario:senha@exemplo.com/eventos"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validar_backend(url, "token-de-teste")
        with self.assertRaises(ValueError):
            validar_backend("https://exemplo.com/eventos", "")
        validar_backend("http://127.0.0.1:8000/eventos", "token-de-teste")


class TestEnvioHTTP(unittest.TestCase):
    def setUp(self):
        self.resposta = {"id": "visita-123"}
        self.status = 200
        self.requisicoes = []
        teste = self

        class Backend(BaseHTTPRequestHandler):
            def do_POST(self):
                corpo = self.rfile.read(int(self.headers["Content-Length"]))
                teste.requisicoes.append((self.path, self.headers, corpo))
                self.send_response(teste.status)
                self.send_header("Content-Type", "application/json")
                if teste.status == 302:
                    self.send_header("Location", "/outro-destino")
                self.end_headers()
                self.wfile.write(json.dumps(teste.resposta).encode())

            def log_message(self, *args):
                pass

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        self.thread = threading.Thread(target=self.servidor.serve_forever)
        self.thread.start()
        self.addCleanup(self.fechar)
        self.url = f"http://127.0.0.1:{self.servidor.server_port}/eventos"
        self.registro = {"id": "visita-123", "origem": "botao",
                         "criado_em": "2026-10-17T12:00:00+00:00", "erro": ""}

    def fechar(self):
        self.servidor.shutdown()
        self.thread.join()
        self.servidor.server_close()

    def test_envia_multipart_mesmo_quando_a_captura_falhou(self):
        enviar_http(self.url, "token-de-teste", self.registro, None)
        _, cabecalhos, corpo = self.requisicoes[0]
        self.assertIn("multipart/form-data", cabecalhos["Content-Type"])
        self.assertEqual(cabecalhos["Authorization"], "Bearer token-de-teste")
        self.assertIn(b'visita-123', corpo)

    def test_envia_a_foto_sem_expor_o_caminho_local(self):
        with tempfile.TemporaryDirectory() as pasta:
            foto = Path(pasta) / "visita-123.jpg"
            foto.write_bytes(b"imagem-simulada")
            enviar_http(self.url, "token-de-teste", self.registro, foto)
        corpo = self.requisicoes[0][2]
        self.assertIn(b"imagem-simulada", corpo)
        self.assertNotIn(pasta.encode(), corpo)

    def test_rejeita_confirmacao_de_outro_evento(self):
        self.resposta = {"id": "outro-evento"}
        with self.assertRaises(ValueError):
            enviar_http(self.url, "token-de-teste", self.registro, None)

    def test_rejeita_json_que_nao_seja_objeto(self):
        self.resposta = ["visita-123"]
        with self.assertRaises(ValueError):
            enviar_http(self.url, "token-de-teste", self.registro, None)

    def test_nao_segue_redirecionamento_do_backend(self):
        self.status = 302
        with self.assertRaises(ValueError):
            enviar_http(self.url, "token-de-teste", self.registro, None)
        self.assertEqual([r[0] for r in self.requisicoes], ["/eventos"])


if __name__ == "__main__":
    unittest.main()
