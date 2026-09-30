"""
Gateway: a porta de entrada do frontend (REST + WebSocket), no seu PC.

Rodar (a partir da raiz do projeto):
    python -m auth_gateway.gateway

Neste mesmo processo rodam:
  - a API HTTP (FastAPI) na porta 8000, para o frontend;
  - o servidor gRPC do Auth na porta 50051;
  - a tarefa de fundo que sincroniza nomes com o Messaging.

O Gateway é o ÚNICO componente que fala com o Discovery E com o Messaging.
Cada chamada tem deadline e o seu próprio try/except: se um serviço cair,
só as rotas que dependem dele falham (com 503), e todo o resto continua.

Documentação interativa das rotas: http://localhost:8000/docs
"""

import asyncio
import base64
import binascii
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import grpc
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from grpc_health.v1 import health_pb2
from pydantic import BaseModel

import config
from auth_gateway import auth, banco, clientes, sincronizacao
from gerado import discovery_pb2, messaging_pb2
from logs import Log

log = Log("GATEWAY")


# =============================================================================
# Ciclo de vida: o que acontece quando o Gateway liga e desliga
# =============================================================================

@asynccontextmanager
async def ciclo_de_vida(app):
    """Liga tudo na subida e desliga tudo na descida do servidor HTTP."""
    banco.criar_tabelas()
    clientes.abrir()
    servidor_auth, saude_auth = await auth.iniciar_servidor_grpc()
    tarefa_fila = asyncio.create_task(sincronizacao.varrer_fila_para_sempre())
    log.ok(f"Gateway HTTP em http://localhost:{config.GATEWAY_PORT}  (site: /  ·  docs: /docs)")
    log.info(f"Discovery em {config.endereco_discovery()} | Messaging em {config.endereco_messaging()}")
    yield
    log.aviso("Desligando...")
    tarefa_fila.cancel()
    await saude_auth.enter_graceful_shutdown()
    await servidor_auth.stop(grace=2)
    await clientes.fechar()


app = FastAPI(title="Gateway — site de namoro gRPC", lifespan=ciclo_de_vida)

# CORS liberado: o frontend (feito depois) pode rodar em outra porta/domínio
# e ainda assim chamar esta API pelo navegador.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def registrar_requisicao(request: Request, chamar_rota):
    """Registra no terminal cada requisição da API, com status e tempo."""
    inicio = time.perf_counter()
    resposta = await chamar_rota(request)
    # Arquivos do frontend (html/css/js) e o /api/status, que o frontend e o
    # painel consultam a cada poucos segundos, ficariam poluindo o log.
    if not request.url.path.startswith("/api/") or request.url.path == "/api/status":
        return resposta
    ms = (time.perf_counter() - inicio) * 1000
    texto = f"{request.method} {request.url.path} -> {resposta.status_code} ({ms:.0f} ms)"
    if resposta.status_code >= 500:
        log.erro(texto)
    elif resposta.status_code >= 400:
        log.aviso(texto)
    else:
        log.info(texto)
    return resposta


# =============================================================================
# Utilitários: sessão, conversão de erros gRPC -> HTTP, conversão para JSON
# =============================================================================

def usuario_logado(x_user_id: str = Header(..., description="user_id retornado no login")):
    """Lê o cabeçalho X-User-Id e confere que o usuário existe (só no banco local).

    É a "sessão" deste projeto: o cliente guarda o user_id do login e o
    envia em toda requisição. Sem token assinado (fora de escopo).
    """
    if not banco.usuario_existe(x_user_id):
        raise HTTPException(401, "Sessão inválida: faça login novamente")
    return x_user_id


# Tradução dos status do gRPC para os status HTTP que o frontend entende.
HTTP_POR_STATUS_GRPC = {
    grpc.StatusCode.INVALID_ARGUMENT: 400,
    grpc.StatusCode.UNAUTHENTICATED: 401,
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.ALREADY_EXISTS: 409,
    grpc.StatusCode.RESOURCE_EXHAUSTED: 413,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.DEADLINE_EXCEEDED: 503,
}


def erro_do_servico(servico, erro):
    """Converte um grpc.RpcError de um serviço em HTTPException com mensagem clara."""
    codigo = erro.code()
    status = HTTP_POR_STATUS_GRPC.get(codigo, 502)
    if status == 503:
        log.erro(f"{servico} indisponível ({codigo.name})")
        return HTTPException(503, f"{servico} indisponível no momento")
    return HTTPException(status, erro.details())


def perfil_para_json(perfil):
    """Perfil gRPC -> dicionário JSON. A foto vira data URL, pronta para um <img src>."""
    foto = base64.b64encode(perfil.foto).decode() if perfil.foto else ""
    return {
        "user_id": perfil.user_id,
        "nome": perfil.nome,
        "bio": perfil.bio,
        "foto": f"data:{perfil.tipo_foto};base64,{foto}" if foto else None,
    }


def mensagem_para_json(m):
    """MensagemChat gRPC -> dicionário JSON."""
    return {"id": m.id, "de_user_id": m.de_user_id, "de_nome": m.de_nome,
            "para_user_id": m.para_user_id, "texto": m.texto, "enviada_em": m.enviada_em}


# =============================================================================
# Auth: cadastro e login (Auth está neste processo: chamada direta)
# =============================================================================

class DadosCadastro(BaseModel):
    email: str
    senha: str
    nome: str
    bio: str = ""
    foto_base64: str        # aceita base64 puro ou data URL ("data:image/png;base64,...")
    extensao_foto: str      # ex.: "png", "jpg"


class DadosLogin(BaseModel):
    email: str
    senha: str


@app.post("/api/cadastro", status_code=201)
async def cadastro(dados: DadosCadastro):
    """Cria a conta. Falha por inteiro (nada gravado) se o Discovery não confirmar o perfil."""
    try:
        foto = base64.b64decode(dados.foto_base64.split(",")[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "foto_base64 inválida")
    try:
        user_id = await auth.cadastrar(dados.email, dados.senha, dados.nome,
                                       dados.bio, foto, dados.extensao_foto)
    except auth.ErroAuth as erro:
        raise HTTPException(HTTP_POR_STATUS_GRPC.get(erro.codigo, 500), erro.mensagem)
    return {"user_id": user_id}


@app.post("/api/login")
async def login(dados: DadosLogin):
    """Confere e-mail/senha localmente e devolve o user_id (a "sessão")."""
    try:
        return {"user_id": auth.entrar(dados.email, dados.senha)}
    except auth.ErroAuth as erro:
        raise HTTPException(401, erro.mensagem)


# =============================================================================
# Aba "Descobrir": só fala com o Discovery
# =============================================================================

@app.get("/api/feed")
async def feed(todos: bool = False, eu: str = Depends(usuario_logado)):
    """Perfis que o usuário ainda não curtiu nem passou (Discovery.GetFeed).

    Com ?todos=true, inclui também quem já foi avaliado ("ver de novo").

    A resposta também é um stream: formato NDJSON (um perfil em JSON por
    linha). Cada perfil que chega do Discovery pelo stream gRPC é repassado
    ao navegador na mesma hora, sem esperar os outros. Numa rede lenta, o
    primeiro cartão aparece em ~1s em vez de esperar o feed inteiro.
    """
    chamada = clientes.discovery.GetFeed(
        discovery_pb2.PedidoFeed(user_id=eu, incluir_avaliados=todos),
        timeout=config.TIMEOUT_STREAM_SEGUNDOS)
    fluxo = chamada.__aiter__()

    # Espera o PRIMEIRO perfil antes de responder: se o Discovery estiver
    # fora, ainda dá tempo de devolver um 503 de verdade (depois que o
    # stream HTTP começa, o status já foi enviado e não muda mais).
    try:
        primeiro = await fluxo.__anext__()
    except StopAsyncIteration:
        primeiro = None  # feed vazio: ninguém novo
    except grpc.RpcError as erro:
        raise erro_do_servico("Discovery", erro)

    async def linhas():
        enviados = 0
        try:
            if primeiro is None:
                return
            yield json.dumps(perfil_para_json(primeiro)) + "\n"
            enviados = 1
            async for perfil in fluxo:
                yield json.dumps(perfil_para_json(perfil)) + "\n"
                enviados += 1
        except grpc.RpcError as erro:
            # Degradação graciosa: o stream caiu no meio. O navegador já
            # recebeu e mostrou os perfis anteriores; só encerramos aqui.
            log.aviso(f"Feed interrompido ({erro.code().name}) depois de {enviados} perfil(is)")
        finally:
            chamada.cancel()  # se o navegador desistir no meio, avisa o Discovery

    return StreamingResponse(linhas(), media_type="application/x-ndjson")


async def _avaliar(rpc, eu, outro_id):
    """Chama Like ou Pass no Discovery."""
    try:
        resposta = await rpc(discovery_pb2.PedidoAvaliacao(de_user_id=eu, para_user_id=outro_id),
                             timeout=config.TIMEOUT_SEGUNDOS)
    except grpc.RpcError as erro:
        raise erro_do_servico("Discovery", erro)
    return {"mensagem": resposta.mensagem}


@app.post("/api/perfis/{outro_id}/curtir")
async def curtir(outro_id: str, eu: str = Depends(usuario_logado)):
    """Curtir: só grava no Discovery. Não abre chat nem chama o Messaging."""
    return await _avaliar(clientes.discovery.Like, eu, outro_id)


@app.post("/api/perfis/{outro_id}/passar")
async def passar(outro_id: str, eu: str = Depends(usuario_logado)):
    """Passar: o perfil some do feed deste usuário."""
    return await _avaliar(clientes.discovery.Pass, eu, outro_id)


@app.get("/api/quem-me-curtiu")
async def quem_me_curtiu(eu: str = Depends(usuario_logado)):
    """Perfis de quem curtiu o usuário (Discovery.QuemMeCurtiu)."""
    perfis = []
    try:
        async for perfil in clientes.discovery.QuemMeCurtiu(
                discovery_pb2.PedidoQuemMeCurtiu(user_id=eu), timeout=config.TIMEOUT_STREAM_SEGUNDOS):
            perfis.append(perfil_para_json(perfil))
    except grpc.RpcError as erro:
        if not perfis:
            raise erro_do_servico("Discovery", erro)
    return perfis


async def _buscar_perfil(user_id):
    """Chama Discovery.GetProfile e devolve o perfil em JSON."""
    try:
        perfil = await clientes.discovery.GetProfile(
            # Prazo de "stream": a resposta traz a foto inteira.
            discovery_pb2.PedidoPerfil(user_id=user_id), timeout=config.TIMEOUT_STREAM_SEGUNDOS)
    except grpc.RpcError as erro:
        raise erro_do_servico("Discovery", erro)
    return perfil_para_json(perfil)


@app.get("/api/meu-perfil")
async def meu_perfil(eu: str = Depends(usuario_logado)):
    """O perfil do próprio usuário (nome, bio, foto)."""
    return await _buscar_perfil(eu)


@app.get("/api/perfis/{outro_id}")
async def perfil(outro_id: str, eu: str = Depends(usuario_logado)):
    """Um perfil qualquer. Usado pelo frontend para mostrar fotos nos chats;
    se o Discovery estiver fora, o frontend mostra só a inicial do nome."""
    return await _buscar_perfil(outro_id)


class DadosPerfil(BaseModel):
    nome: Optional[str] = None  # None = não alterar
    bio: Optional[str] = None


@app.patch("/api/meu-perfil")
async def editar_perfil(dados: DadosPerfil, eu: str = Depends(usuario_logado)):
    """Edita nome/bio no Discovery; se o nome mudou, sincroniza a cópia do Messaging."""
    pedido = discovery_pb2.PedidoAtualizarPerfil(user_id=eu)
    if dados.nome is not None:
        pedido.nome = dados.nome
    if dados.bio is not None:
        pedido.bio = dados.bio

    # 1º o Discovery, que é o DONO do perfil. Se falhar, nada mais acontece.
    try:
        await clientes.discovery.UpdateProfile(pedido, timeout=config.TIMEOUT_SEGUNDOS)
    except grpc.RpcError as erro:
        raise erro_do_servico("Discovery", erro)

    resposta = {"mensagem": "Perfil atualizado"}
    # 2º a cópia do nome no Messaging. Uma falha aqui NÃO desfaz nada nem
    # vira erro para o usuário: o nome vai para a fila e chega depois.
    if dados.nome is not None:
        entregue = await sincronizacao.sincronizar_nome(eu, dados.nome.strip())
        resposta["nome_nos_chats"] = "sincronizado" if entregue else "pendente"
    return resposta


# =============================================================================
# Aba "Chats": só fala com o Messaging
# =============================================================================

@app.get("/api/conversas")
async def conversas(eu: str = Depends(usuario_logado)):
    """Conversas do usuário, da mais recente para a mais antiga (Messaging.ListarConversas)."""
    lista = []
    try:
        async for c in clientes.messaging.ListarConversas(
                messaging_pb2.PedidoListarConversas(user_id=eu), timeout=config.TIMEOUT_SEGUNDOS):
            lista.append({"outro_user_id": c.outro_user_id, "outro_nome": c.outro_nome,
                          "ultima_mensagem": c.ultima_mensagem, "ultima_em": c.ultima_em})
    except grpc.RpcError as erro:
        if not lista:
            raise erro_do_servico("Messaging", erro)
    return lista


@app.websocket("/ws/chat/{outro_id}")
async def chat(websocket: WebSocket, outro_id: str, user_id: str):
    """
    Ponte entre o WebSocket do navegador e o stream bidirecional gRPC do Messaging.

    Conectar em: ws://localhost:8000/ws/chat/<outro_id>?user_id=<meu_id>
    (navegadores não deixam enviar cabeçalhos no WebSocket, então o user_id
    vai na URL). Enviar: {"texto": "..."}. Receber: histórico + mensagens
    novas no mesmo formato de mensagem_para_json, ou {"erro": "..."}.

    O user_id do outro já veio no feed, então não é preciso perguntar nada ao
    Discovery: abrir um chat funciona mesmo com o Discovery fora do ar.
    """
    if not banco.usuario_existe(user_id):
        await websocket.close(code=4401, reason="Sessão inválida")
        return
    await websocket.accept()
    log.info(f"WebSocket de chat aberto: {user_id} -> {outro_id}")

    # Um stream bidirecional gRPC: podemos escrever (write) e ler (async for)
    # ao mesmo tempo, de forma independente.
    chamada = clientes.messaging.Chat(timeout=config.DURACAO_MAXIMA_CHAT_SEGUNDOS)

    async def do_navegador_para_o_grpc():
        # Cada texto digitado no navegador vira uma mensagem no stream gRPC.
        while True:
            dados = await websocket.receive_json()
            await chamada.write(messaging_pb2.EnvioChat(
                de_user_id=user_id, para_user_id=outro_id, texto=str(dados.get("texto", ""))))

    async def do_grpc_para_o_navegador():
        # A 1ª mensagem abre a conversa; depois, tudo que o Messaging mandar
        # (histórico e mensagens novas) é repassado ao navegador.
        await chamada.write(messaging_pb2.EnvioChat(de_user_id=user_id, para_user_id=outro_id))
        async for mensagem in chamada:
            await websocket.send_json(mensagem_para_json(mensagem))

    # As duas direções rodam em paralelo. Quando qualquer uma termina (o
    # navegador fechou, ou o Messaging caiu), a outra é cancelada.
    tarefas = [asyncio.create_task(do_navegador_para_o_grpc()),
               asyncio.create_task(do_grpc_para_o_navegador())]
    terminadas, pendentes = await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
    for tarefa in pendentes:
        tarefa.cancel()
    chamada.cancel()  # avisa o Messaging que este stream acabou

    erro = next((t.exception() for t in terminadas if t.exception()), None)
    try:
        if isinstance(erro, grpc.RpcError):
            log.erro(f"Chat {user_id} -> {outro_id} interrompido: Messaging {erro.code().name}")
            await websocket.send_json({"erro": "Messaging indisponível no momento"})
            await websocket.close(code=1011)
        else:
            await websocket.close()
    except Exception:
        pass  # o navegador já tinha fechado
    log.info(f"WebSocket de chat fechado: {user_id} -> {outro_id}")


# =============================================================================
# Status: útil para o frontend mostrar avisos ("chat fora do ar") e para o painel
# =============================================================================

async def _saude(stub, canal, servico):
    """Health Check padrão do gRPC com deadline; nunca lança erro.

    Um prazo estourado (DEADLINE_EXCEEDED) é ambíguo pela internet: pode ser
    rede lenta OU serviço parado cujo "conexão recusada" nunca chegou até
    aqui (um firewall no caminho descarta). Quem desempata é o estado da
    conexão gRPC: se ela continua PRONTA (READY), o serviço está lá e só
    demorou -> "LENTO". Se caiu ou está tentando reconectar, não há ninguém
    do outro lado -> fora do ar. Um "systemctl stop" avisa os clientes ao
    desligar (HTTP/2 GOAWAY), então a conexão sai de READY na mesma hora.
    """
    try:
        resposta = await stub.Check(health_pb2.HealthCheckRequest(service=servico),
                                    timeout=config.TIMEOUT_HEALTH_SEGUNDOS)
        return health_pb2.HealthCheckResponse.ServingStatus.Name(resposta.status)
    except grpc.RpcError as erro:
        if erro.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            if canal.get_state(try_to_connect=False) == grpc.ChannelConnectivity.READY:
                return "LENTO"
            return "FORA DO AR (SEM CONEXÃO)"
        return f"FORA DO AR ({erro.code().name})"


@app.get("/api/status")
async def status():
    """Situação de cada serviço e quantos nomes aguardam sincronização."""
    discovery, messaging = await asyncio.gather(
        _saude(clientes.saude_discovery, clientes.canal_discovery, "discovery.Discovery"),
        _saude(clientes.saude_messaging, clientes.canal_messaging, "messaging.Messaging"))
    return {"auth": "SERVING", "discovery": discovery, "messaging": messaging,
            "nomes_pendentes": banco.contar_pendencias()}


# =============================================================================
# Frontend: o Gateway também entrega os arquivos da pasta frontend/.
# Montado POR ÚLTIMO, para que /api/* e /ws/* acima tenham prioridade.
# Abrir no navegador: http://localhost:8000
# =============================================================================

PASTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if PASTA_FRONTEND.exists():
    app.mount("/", StaticFiles(directory=PASTA_FRONTEND, html=True), name="frontend")


if __name__ == "__main__":
    # log_level="warning": os logs de cada requisição já são feitos pelo
    # middleware acima, no mesmo formato dos outros serviços.
    uvicorn.run(app, host=config.ENDERECO_ESCUTA, port=config.GATEWAY_PORT, log_level="warning")
