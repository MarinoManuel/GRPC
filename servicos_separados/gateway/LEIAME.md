# Gateway + Auth + site (porta 8000)

A porta de entrada: entrega o site, recebe REST/WebSocket do navegador e fala
gRPC com o Discovery e o Messaging. O Auth (login e cadastro) roda no mesmo
processo, com gRPC na porta 50051.

```
gateway/                    <- esta pasta (a "raiz" do serviço)
├── iniciar.bat             <- Windows: dois cliques (site em http://localhost:8000)
├── painel.bat              <- painel de saúde dos serviços
├── requirements.txt
├── config.py               <- ONDE ESTÃO o Discovery e o Messaging (edite aqui)
├── logs.py
├── gerado/                 <- código gerado dos 3 .proto (não editar)
├── auth_gateway/
│   ├── gateway.py          <- rotas REST/WebSocket -> chamadas gRPC
│   ├── auth.py             <- cadastro/login + servidor gRPC do Auth
│   ├── clientes.py         <- canais gRPC para o Discovery e o Messaging
│   ├── sincronizacao.py    <- fila de retry dos nomes (backoff exponencial)
│   ├── banco.py            <- SQLite (auth.db é criado aqui na 1ª execução)
│   └── seed.py             <- cria as 5 contas de demonstração
├── frontend/               <- o site (HTML, CSS, JS)
└── painel/painel.py        <- painel de saúde no terminal
```

## 1. Apontar para os serviços (config.py)

```python
DISCOVERY_HOST = "82.112.240.107"    # nuvem; "localhost" se estiver neste PC; ou o IP de outro PC
MESSAGING_HOST = "129.151.186.241"
```

Só esta pasta precisa saber os endereços. Os serviços não precisam saber o do Gateway.

## 2. Iniciar

Dois cliques em `iniciar.bat`. Ou, no terminal, **dentro desta pasta**:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m auth_gateway.seed       # contas ana@seed.com, beatriz@seed.com... senha 123
python -m auth_gateway.gateway    # site em http://localhost:8000
python -m painel.painel           # (opcional, outro terminal)
```

## Contas de login

Os logins ficam **nesta pasta**, em `auth_gateway/auth.db`, e não no Discovery.
- Sem esse arquivo, só existem as 5 contas do seed (senha `123`).
- Para ter as mesmas contas de outro Gateway, copie o `auth.db` dele para cá.
  Os perfis dessas contas precisam existir no Discovery que este Gateway usa.

## Outros aparelhos acessarem o site

Use `http://IP-DESTE-PC:8000` (com o `:8000`) e libere a porta 8000/TCP no firewall.

## Cuidado ao trocar os endereços

Se houver nomes na fila de sincronização (painel: "Fila de nomes" > 0), eles
serão entregues ao endereço que estiver no `config.py` quando o Gateway rodar.
Troque os endereços com o Gateway desligado.
