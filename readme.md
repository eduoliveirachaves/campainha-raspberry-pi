# Campainha com Raspberry Pi

Parte embarcada de uma campainha com registro de visitas, feita para a disciplina de Desenvolvimento de Sistemas Móveis e Embarcados da UFSC.

O programa usa Python para ler um botão e um sensor PIR, tirar uma foto com a câmera CSI e acender um LED durante a captura. Os eventos ficam salvos na placa em SQLite. O envio para um backend é opcional, configurado por `BACKEND_URL` e `BACKEND_TOKEN`.

No Raspberry Pi OS, instale as dependências e execute:

```sh
sudo apt install python3-gpiozero python3-picamera2 python3-requests
python3 campainha.py
```

Para rodar os testes sem a placa, basta ter Python e Requests instalados:

```sh
python3 -m unittest discover -v
```

O código ainda precisa ser validado no hardware. O backend e o aplicativo móvel serão desenvolvidos nas próximas etapas.
