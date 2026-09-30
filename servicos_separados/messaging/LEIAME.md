# Messaging (porta 50053)

Dono das mensagens e de uma cópia (cache) dos nomes. Não chama nenhum outro serviço.

```
messaging/                  <- esta pasta (a "raiz" do serviço)
├── iniciar.bat             <- Windows: dois cliques
├── requirements.txt
├── config.py  logs.py      <- porta e logs
├── gerado/                 <- código gerado do messaging.proto (não editar)
└── messaging/              <- o serviço
    ├── servidor.py         <- os rpc: AtualizarNome, Chat (bidirecional), ListarConversas
    ├── banco.py            <- SQLite (messaging.db é criado aqui na 1ª execução)
    ├── chat_terminal.py    <- chat interativo no terminal (demonstração)
    ├── testar_cliente.py   <- testa o serviço desta máquina
    └── messaging.service   <- serviço systemd (Linux)
```

## Windows

Dois cliques em `iniciar.bat`. Ou, no terminal, **dentro desta pasta**:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m messaging.servidor
```

O Messaging não tem seed: o banco começa vazio e os nomes chegam pelo Gateway.

## Linux

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m messaging.servidor
```

Para rodar em segundo plano, veja `messaging/DEPLOY.md` e ajuste no
`messaging/messaging.service` o usuário (`User=`) e a pasta (`WorkingDirectory=`).

## Para outros PCs acessarem

Libere a porta **50053/TCP** no firewall. No Windows, PowerShell como administrador:

```powershell
New-NetFirewallRule -DisplayName "gRPC Messaging" -Direction Inbound -Protocol TCP -LocalPort 50053 -Action Allow
```

No PC do Gateway, coloque o IP desta máquina em `MESSAGING_HOST` no `config.py`.

## Testar sozinho

Com o servidor rodando, em outro terminal nesta pasta (testa o Messaging **desta máquina**):

```powershell
python -m messaging.testar_cliente                   # teste automático
python -m messaging.chat_terminal ana bia "Ana"      # chat ao vivo (abra outro com: bia ana "Bia")
```
