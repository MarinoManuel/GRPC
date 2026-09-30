# Discovery (porta 50052)

Dono de perfis (nome, bio, foto) e curtidas. Não chama nenhum outro serviço.

```
discovery/                  <- esta pasta (a "raiz" do serviço)
├── iniciar.bat             <- Windows: dois cliques
├── requirements.txt
├── config.py  logs.py      <- porta e logs
├── gerado/                 <- código gerado do discovery.proto (não editar)
└── discovery/              <- o serviço
    ├── servidor.py         <- os rpc: CreateProfile, UpdateProfile, GetProfile, GetFeed, Like, Pass, QuemMeCurtiu
    ├── banco.py            <- SQLite (discovery.db é criado aqui na 1ª execução)
    ├── seed.py             <- cria os 5 perfis de demonstração
    ├── fotos/              <- fotos dos perfis de seed
    ├── testar_cliente.py   <- testa o serviço desta máquina
    └── discovery.service   <- serviço systemd (Linux)
```

## Windows

Dois cliques em `iniciar.bat`. Ou, no terminal, **dentro desta pasta**:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m discovery.seed        # 1ª vez (se já existir, só ignora)
python -m discovery.servidor
```

## Linux

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m discovery.seed
.venv/bin/python -m discovery.servidor
```

Para rodar em segundo plano, veja `discovery/DEPLOY.md` e ajuste no
`discovery/discovery.service` o usuário (`User=`) e a pasta (`WorkingDirectory=`).

## Para outros PCs acessarem

Libere a porta **50052/TCP** no firewall. No Windows, PowerShell como administrador:

```powershell
New-NetFirewallRule -DisplayName "gRPC Discovery" -Direction Inbound -Protocol TCP -LocalPort 50052 -Action Allow
```

No PC do Gateway, coloque o IP desta máquina em `DISCOVERY_HOST` no `config.py`.

## Testar sozinho

Com o servidor rodando, em outro terminal nesta pasta:
`python -m discovery.testar_cliente`. Ele testa o Discovery **desta máquina**
(`localhost`) e cria um "Usuário de Teste" no banco local.

## Dados

Os dados ficam em `discovery/discovery.db` e `discovery/fotos_usuarios/`.
Para levar os perfis para outra máquina, copie esses dois junto com a pasta.
