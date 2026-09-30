# Site de namoro com gRPC: Sistemas Distribuídos

Demonstração dos **4 tipos de chamada gRPC** e do **isolamento de falhas**
entre serviços. Três serviços independentes, cada um com o seu próprio SQLite:

```
                 ┌──────────────── seu PC ────────────────┐
  navegador ───► │  Gateway (FastAPI :8000)  +  Auth (gRPC :50051)
  (REST / WS)    │   └─ fila de nomes pendentes (retry com backoff)
                 └──────────┬────────────────────┬─────────┘
                            │ gRPC               │ gRPC
                  ┌─────────▼─────────┐  ┌───────▼──────────┐
                  │ Discovery :50052  │  │ Messaging :50053 │
                  │ perfis + likes    │  │ mensagens + nomes│
                  │ (VPS Hostinger)   │  │ (Oracle Cloud)   │
                  └───────────────────┘  └──────────────────┘
        Discovery e Messaging NUNCA se falam: só o Gateway fala com cada um.
```

| Tipo de chamada | Onde aparece |
|---|---|
| Unário | `UpdateProfile`, `GetProfile`, `Like`, `Pass`, `AtualizarNome`, `Register`, `Login` |
| Server streaming | `GetFeed`, `QuemMeCurtiu`, `ListarConversas` |
| Client streaming | `CreateProfile` (foto enviada em pedaços de 32 KB) |
| Bidirecional | `Chat` |

## Estrutura

| Pasta/arquivo | O que é |
|---|---|
| `config.py` | Único lugar com endereços, portas e timeouts |
| `logs.py` | Logs coloridos padronizados |
| `protos/` + `gerar_protos.py` | Contratos `.proto` e o gerador de código (saída em `gerado/`) |
| `discovery/` | Serviço Discovery + seed + teste + deploy ([DEPLOY.md](discovery/DEPLOY.md)) |
| `messaging/` | Serviço Messaging + chat de terminal + teste + deploy ([DEPLOY.md](messaging/DEPLOY.md)) |
| `auth_gateway/` | Auth + Gateway REST/WebSocket + fila de sincronização de nomes + teste |
| `painel/` | Painel de saúde ao vivo + teste automático de resiliência |
| `frontend/` | Site "faísca" (HTML + CSS + JS puro, sem build), servido pelo próprio Gateway |

## O site (frontend)

Com os três serviços no ar, abra **http://localhost:8000** no navegador.
Não há nada para instalar ou compilar: o Gateway entrega os arquivos da pasta `frontend/`.

- **Entrar:** com uma conta de seed (`ana@seed.com`, `beatriz@seed.com`, `carla@seed.com`,
  `daniela@seed.com`, `elisa@seed.com`, todas com senha `123`) ou crie uma conta com foto.
- **Descobrir:** as setas (ou `←` `→`) voltam e avançam entre os perfis. Arrastar o cartão
  para a direita curte e para a esquerda passa (ou `C` / `X`); `M` abre o chat.
  Ao voltar para alguém já avaliado, o cartão mostra "Você curtiu" ou "Você passou".
- **Curtidas:** mural de quem curtiu você.
- **Chats:** conversa em tempo real (WebSocket no navegador, stream bidirecional gRPC por trás).
- **Perfil:** edite nome e bio. Se o Messaging estiver fora, o nome novo entra na fila de
  retry do Gateway, e um aviso aparece quando ele chega aos chats.
- **Letreiro do sistema** (canto inferior esquerdo, ou pílula no topo no celular):
  a saúde de cada serviço e da fila, atualizada a cada 3s.

A interface não mostra detalhes de implementação para o usuário, que ficam para a apresentação.
Só o letreiro do sistema cita os serviços pelo nome. Quando um serviço cai, só as abas
que dependem dele mostram uma tela de "indisponível no momento". O resto do site continua funcionando, e a tela se recupera sozinha
quando o serviço volta. Durante a demonstração, deixe o site aberto e derrube os serviços
pelo terminal.

## Rodar tudo localmente

```powershell
.venv\Scripts\activate
python gerar_protos.py                  # só depois de mudar um .proto

# Uma vez só (dados iniciais):
python -m discovery.seed
python -m auth_gateway.seed             # logins ana@seed.com / 123, beatriz@seed.com / 123 ...

# Um terminal para cada:
python -m discovery.servidor
python -m messaging.servidor
python -m auth_gateway.gateway
python -m painel.painel
```

Testes (com os serviços no ar):

```powershell
python -m discovery.testar_cliente      # Discovery sozinho
python -m messaging.testar_cliente      # Messaging sozinho
python -m auth_gateway.testar_gateway   # fluxo completo via REST + WebSocket
```

Teste automático de resiliência (com os serviços **parados**; ele sobe e derruba tudo sozinho):

```powershell
python -m painel.testar_resiliencia
```

## Roteiro da demonstração ao vivo

Prepare **5 terminais**: Discovery, Messaging, Gateway, painel e um livre
para comandos. Suba os três serviços e o painel. Tudo aparece verde.

No terminal livre, entre em uma sessão Python para usar o Gateway:

```powershell
python
>>> from auth_gateway.testar_gateway import chamar
>>> ana = chamar("POST", "/api/login", {"email": "ana@seed.com", "senha": "123"})[1]["user_id"]
>>> bia = chamar("POST", "/api/login", {"email": "beatriz@seed.com", "senha": "123"})[1]["user_id"]
```

**1. Os 4 tipos de chamada**
- Feed (server streaming): `[p["nome"] for p in chamar("GET", "/api/feed", user_id=ana)[1]]`. No log do Discovery aparece o stream.
- Chat (bidirecional): abra dois terminais com
  `python -m messaging.chat_terminal seed-1 seed-2` e `python -m messaging.chat_terminal seed-2 seed-1`,
  e converse. As mensagens chegam em tempo real nos dois lados.
- Cadastro (client streaming): `python -m auth_gateway.testar_gateway`. No log do Discovery aparece "foto recebida em 3 pedaços".

**2. O Messaging cai, e a aba Descobrir continua**
1. Ctrl+C no terminal do Messaging. O painel fica vermelho na linha do Messaging e o chat de terminal avisa que a conexão caiu.
2. `chamar("GET", "/api/feed", user_id=ana)[0]` responde `200`: o feed funciona.
3. `chamar("GET", "/api/conversas", user_id=ana)` responde `503`, "Messaging indisponível no momento".

**3. A fila de retry sincroniza sozinha**
1. Com o Messaging ainda fora: `chamar("PATCH", "/api/meu-perfil", {"nome": "Ana Clara"}, user_id=ana)`
   responde `200` com `"nome_nos_chats": "pendente"`.
2. O painel mostra **1 nome pendente**. No log do Gateway, as tentativas aparecem com espera dobrando: 2s, 4s, 8s...
3. Suba o Messaging de novo. Em poucos segundos o log mostra "entregue na tentativa N" e o painel volta a **0 pendentes**.
4. `chamar("GET", "/api/conversas", user_id=bia)[1]` mostra a conversa com **"Ana Clara"**.

**4. O Discovery cai, e a aba Chats continua**
1. Ctrl+C no Discovery. O painel fica vermelho na linha do Discovery.
2. O chat de terminal continua funcionando normalmente, e `/api/conversas` responde `200`.
3. `/api/feed` responde `503`.
4. Um cadastro durante a queda falha com `503`, e o login com aquele e-mail também falha:
   **nada foi gravado**, porque o Auth só grava a credencial depois que o Discovery confirma.

**Pontos para explicar durante a demo**
- O Discovery e o Messaging não têm nenhuma dependência entre si. Não é só um try/except: um nem conhece o outro.
- Toda chamada do Gateway tem deadline, então nada fica esperando para sempre.
- A reconexão automática do gRPC religa a conexão, mas não reenvia a chamada que falhou. Por isso a fila existe.

## API do Gateway (para o frontend)

Base: `http://<host>:8000`. JSON em tudo. Documentação interativa em `/docs`.
Depois do login, envie o cabeçalho **`X-User-Id: <user_id>`** em todas as rotas `/api/*`
(menos cadastro e login). Um `user_id` desconhecido recebe `401`.

| Método e rota | Corpo | Resposta |
|---|---|---|
| `POST /api/cadastro` | `{email, senha, nome, bio, foto_base64, extensao_foto}` (base64 puro ou data URL; máx. 3 MB) | `201 {user_id}` |
| `POST /api/login` | `{email, senha}` | `{user_id}` |
| `GET /api/feed` (`?todos=true` inclui os já avaliados) | | **NDJSON**: um `{user_id, nome, bio, foto}` por linha, enviado assim que cada perfil chega do Discovery. `foto` vem como data URL para usar direto no `<img src>` |
| `GET /api/meu-perfil` | | `{user_id, nome, bio, foto}` |
| `GET /api/perfis/{id}` | | `{user_id, nome, bio, foto}` |
| `POST /api/perfis/{id}/curtir` | | `{mensagem}` |
| `POST /api/perfis/{id}/passar` | | `{mensagem}` |
| `GET /api/quem-me-curtiu` | | `[{user_id, nome, bio, foto}]` |
| `PATCH /api/meu-perfil` | `{nome?, bio?}` | `{mensagem, nome_nos_chats?: "sincronizado" \| "pendente"}` |
| `GET /api/conversas` | | `[{outro_user_id, outro_nome, ultima_mensagem, ultima_em}]` |
| `GET /api/status` | | `{auth, discovery, messaging, nomes_pendentes}` |
| `WS /ws/chat/{outro_id}?user_id=<meu_id>` | enviar `{"texto": "..."}` | recebe o histórico e depois as mensagens novas: `{id, de_user_id, de_nome, para_user_id, texto, enviada_em}`; ou `{"erro": "..."}` se o Messaging cair |

Erros vêm como `{"detail": "mensagem"}` com status `400`, `401`, `404`, `409`,
`413` ou `503`. O `503` quer dizer "este serviço está fora; o resto do app continua".
Datas estão em ISO 8601, UTC.
