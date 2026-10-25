# Campainha com registro fotográfico e notificações

Projeto de Gabriela da Silva de Jesus e Eduardo de Oliveira Chaves para a disciplina INE5670, UFSC, 2026.2.

A campainha fotografa o visitante ao pressionar o botão e emite um aviso sonoro. Consulta de fotos e notificações no aplicativo móvel compõem a integração prevista. PIR e LED são melhorias opcionais.

## Entrega

[Baixar o ZIP para anexar](entrega/campainha-entrega.zip) · [Consultar a proposta em PDF](entrega/campainha-raspberry-pi-projeto.pdf)

O ZIP destinado ao professor contém somente a proposta em PDF e `main.py`, o programa embarcado completo para botão, buzzer e câmera. Não inclui testes, README, scripts de apoio, dependências ou facilitadores de transferência.

## Organização

| Pasta | Conteúdo |
|---|---|
| `src/` | Todo o código fonte e as dependências |
| `entrega/` | PDF vigente e pacote para anexar |

Na pasta local também existem `docs/` (edição do PDF, figuras e materiais da disciplina), `scripts/` (atalhos pessoais do terminal) e `arquivo/` (versões anteriores preservadas). Essas pastas locais não fazem parte da entrega nem do repositório público.

## Fontes

| Arquivo | Responsabilidade |
|---|---|
| `src/main.py` | Programa embarcado completo: botão, buzzer, captura, fila e registros de eventos |
| `src/enviar_fotos.py` | Facilitador de envio das fotos ao computador, com até três tentativas por arquivo |
| `src/receber_fotos.py` | Receptor das fotos no computador |
| `src/run.sh` | Inicia o programa embarcado e o facilitador de envio |
| `src/preparar_recebimento.sh` | Prepara o receptor e o túnel SSH iniciado pelo computador |
| `src/requirements.txt` | Dependência Python de transporte HTTP |

`main.py` reúne a lógica que antes estava dividida entre dois módulos. Ele funciona sem os facilitadores de transferência.

## Executar no Raspberry Pi

Use Raspberry Pi OS com Python 3, GPIO Zero e rpicam-apps. Instale os pacotes do sistema:

```sh
sudo apt install python3-gpiozero python3-requests rpicam-apps
cd src
python3 main.py
```

Após a mensagem `PRONTO`, pressione o botão. Ctrl+C encerra o programa.

- Botão: BCM17, pino físico 11, conectado ao GND; pull-up interno.
- Comando do buzzer: BCM18, pino físico 12, PWM de 2 kHz; GND comum.
- Câmera OV5647: conector CSI.

Dimensione a interface de acionamento do buzzer conforme sua tensão e corrente nominal. As fotos usam o formato `HH-MM-SS__Dia-Mes.jpg`, e os logs exibem somente o horário.

## Facilitador de transferência

Os facilitadores são separados do comportamento embarcado. O computador inicia a conexão SSH e prepara um receptor acessível pelo túnel. A configuração de conta, chave e pasta remota deve ser adaptada ao ambiente antes do uso; chaves privadas, configuração de autenticação, fotos e bancos não são distribuídos.

Com o receptor preparado, execute `run.sh` na pasta dos fontes no Raspberry Pi. As fotos são enviadas com no máximo três tentativas por arquivo. Ao esgotar o limite, a foto permanece na placa. Esse receptor de apoio não implementa o histórico móvel nem as notificações futuras.
