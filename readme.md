# Campainha com registro fotográfico e notificações

Projeto da disciplina INE5670 - Desenvolvimento de Sistemas Móveis e Embarcados, UFSC, 2026.2.

**Gabriela da Silva de Jesus e Eduardo de Oliveira Chaves.**

A campainha registra uma foto quando o visitante pressiona o botão e fornece um aviso sonoro pelo buzzer. O Raspberry Pi salva o evento e a imagem localmente. O projeto integrador prevê um backend e um aplicativo móvel para consultar fotos e histórico e receber notificações de novas visitas.

O escopo físico principal é botão, buzzer e câmera CSI em um Raspberry Pi 3 Model B+. PIR e LED são possíveis melhorias até a entrega final. Backend, aplicativo e notificações ainda serão desenvolvidos. A [proposta em PDF](campainha-raspberry-pi-projeto.pdf) descreve a arquitetura e as etapas previstas.

## Arquivos

| Arquivo | Função |
|---|---|
| `main.py` | Programa embarcado: botão, buzzer e câmera |
| `campainha.py` | Fila de eventos, SQLite, captura e retenção local |
| `run.sh` | Inicia o projeto e o facilitador separado de transferência |
| `enviar_fotos.py` | Envia ao computador as fotos pendentes, com até três tentativas por foto |
| `scripts/preparar_recebimento.sh` | Prepara o receptor no computador e o túnel SSH |
| `scripts/receber_fotos.py` | Recebe os arquivos em `~/Pictures/embarcados/` |

## Hardware e dependências

- Botão: GPIO17/BCM17, pino físico 11, ao GND do pino 9; pull-up interno.
- Comando do buzzer: GPIO18/BCM18, pino físico 12, PWM de 2 kHz; GND comum.
- Câmera OV5647: interface CSI.

Dimensione a interface de acionamento do buzzer conforme sua tensão e corrente nominal. O PWM não limita a corrente da carga. O PDF apresenta o esquema funcional e essa condição de dimensionamento.

No Raspberry Pi OS:

```sh
sudo apt install python3-gpiozero python3-requests rpicam-apps
```

O programa usa `/usr/bin/python3` e `rpicam-still`, com alternativa `libcamera-still` para instalações compatíveis. `requirements.txt` registra a dependência Python de transporte HTTP; GPIO e câmera devem usar os pacotes do Raspberry Pi OS.

## Executar apenas o programa embarcado

Coloque `main.py` e `campainha.py` na pasta `~/projeto` do Raspberry:

```sh
cd ~/projeto
/usr/bin/python3 main.py
```

Após a mensagem `PRONTO`, pressione o botão. Os eventos ficam em `~/projeto/fotos/eventos.sqlite3` e as imagens em `~/projeto/fotos/`. Esse modo funciona sem o receptor do computador. Use Ctrl+C para encerrar.

As fotos usam `HH-MM-SS__Dia-Mes.jpg`; a data completa e o identificador do evento ficam no SQLite. Os logs mostram somente `HH:MM:SS`. Capturas com o mesmo nome aguardam outro segundo para preservar a foto anterior.

## Executar com envio automático ao computador

Este facilitador de bancada é separado do programa embarcado. Ele usa uma conexão iniciada pelo computador e um receptor local acessível pelo túnel SSH; não exige servidor SSH no computador. O Raspberry não recebe a chave privada do computador e o agente SSH não é encaminhado.

No computador Linux, instale o cliente OpenSSH e Python 3. Se ainda não houver a chave dedicada, crie-a e instale somente a chave pública no Raspberry:

```sh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_rasp
ssh-copy-id -i ~/.ssh/id_ed25519_rasp.pub admin@raspberrypi.local
```

Se proteger a chave com senha, carregue-a no agente SSH local para o uso automático. O facilitador usa a conta `admin`, a pasta `~/projeto` e a chave acima.

Copie os quatro arquivos de execução para o Raspberry e prepare o recebimento a partir da pasta do projeto no computador:

```sh
ssh -i ~/.ssh/id_ed25519_rasp admin@raspberrypi.local 'mkdir -p ~/projeto'
scp -i ~/.ssh/id_ed25519_rasp main.py campainha.py run.sh enviar_fotos.py admin@raspberrypi.local:projeto/
bash scripts/preparar_recebimento.sh
ssh -i ~/.ssh/id_ed25519_rasp admin@raspberrypi.local
```

O script resolve `raspberrypi.local` a cada preparação, com verificação de resposta em até dois segundos. Também aceita o IP atual como argumento. Ele inicia o receptor em `127.0.0.1:8766`, abre o túnel e gera a configuração privada `pc.json` na placa.

No Raspberry:

```sh
cd ~/projeto
chmod +x run.sh
./run.sh
```

O `run.sh` verifica o receptor antes de iniciar os dois processos. O envio usa no máximo **três tentativas por foto**, separadas por pelo menos cinco segundos desde o início da tentativa anterior. O contador persiste após reinício. Fotos ainda não tentadas têm prioridade sobre novas tentativas de arquivos com falha. Ao esgotar o limite, a foto permanece no Raspberry para recuperação manual. Encerrar com Ctrl+C para captura e envio.

O computador precisa permanecer ligado e com o túnel disponível durante esse modo. O receptor grava as imagens em `~/Pictures/embarcados/`; ele não implementa o histórico móvel nem as notificações do projeto integrador.

## Retenção e configuração privada

O limite local padrão é de 200 imagens. Somente fotos marcadas como enviadas podem ser removidas pela retenção. Se todas estiverem pendentes, novos eventos podem ser registrados com erro de captura por falta de espaço disponível na política. O histórico do banco ainda não tem rotação.

Chaves, `pc.json`, bancos, logs e fotos de visitantes não fazem parte do repositório nem da entrega de fontes. O pacote contém os programas e a proposta; a demonstração física será presencial.
