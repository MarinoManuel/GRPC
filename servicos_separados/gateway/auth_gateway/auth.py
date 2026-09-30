"""
Serviço Auth: cadastro e login.

As regras ficam nas funções cadastrar() e entrar(), usadas de dois jeitos:
  - pelas rotas REST do Gateway (mesmo processo: chamada direta de função;
    não faz sentido passar pela rede para falar consigo mesmo);
  - pelo servidor gRPC do Auth (porta 50051), que expõe as mesmas regras
    como Register/Login e responde ao Health Check do painel.
"""

import uuid

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

import config
from auth_gateway import banco, clientes, sincronizacao
from gerado import auth_pb2, auth_pb2_grpc, discovery_pb2
from logs import Log

log = Log("AUTH")

TAMANHO_PEDACO = 32 * 1024  # a foto vai ao Discovery em pedaços de 32 KB


class ErroAuth(Exception):
    """Erro de regra de negócio do Auth, já com o status gRPC adequado."""

    def __init__(self, codigo, mensagem):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _pedacos_do_perfil(user_id, nome, bio, foto, extensao):
    """Mensagens do CreateProfile: primeiro os dados, depois a foto fatiada."""
    yield discovery_pb2.PedacoCadastro(dados=discovery_pb2.DadosPerfil(
        user_id=user_id, nome=nome, bio=bio, extensao_foto=extensao))
    for inicio in range(0, len(foto), TAMANHO_PEDACO):
        yield discovery_pb2.PedacoCadastro(pedaco_foto=foto[inicio:inicio + TAMANHO_PEDACO])


async def cadastrar(email, senha, nome, bio, foto, extensao_foto):
    """Cria o perfil no Discovery e, só se der certo, grava a credencial. Retorna o user_id."""
    email = email.strip().lower()
    nome = nome.strip()
    if not email or not senha or not nome:
        raise ErroAuth(grpc.StatusCode.INVALID_ARGUMENT, "email, senha e nome são obrigatórios")
    if not foto:
        raise ErroAuth(grpc.StatusCode.INVALID_ARGUMENT, "A foto é obrigatória")
    # Checa o e-mail ANTES de chamar o Discovery, para não criar lá um
    # perfil de alguém que nem conseguiria se cadastrar aqui.
    if banco.email_existe(email):
        raise ErroAuth(grpc.StatusCode.ALREADY_EXISTS, "E-mail já cadastrado")

    user_id = str(uuid.uuid4())

    # ORDEM ESTRITA: 1º o serviço externo, 2º a escrita local.
    # Se o Discovery falhar (fora do ar, timeout, dado inválido), saímos
    # aqui e NADA foi gravado neste banco. Como a escrita local só acontece
    # depois da confirmação, nunca existe um cadastro "pela metade" para
    # desfazer, e por isso não há rollback manual em lugar nenhum.
    try:
        resposta = await clientes.discovery.CreateProfile(
            _pedacos_do_perfil(user_id, nome, bio, foto, extensao_foto),
            timeout=config.TIMEOUT_STREAM_SEGUNDOS)
    except grpc.RpcError as erro:
        log.erro(f"Cadastro de {email} cancelado: Discovery respondeu {erro.code().name}. Nada foi gravado.")
        if erro.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
            raise ErroAuth(grpc.StatusCode.UNAVAILABLE,
                           "Discovery indisponível: cadastro cancelado, nada foi gravado")
        raise ErroAuth(erro.code(), erro.details())

    if not banco.inserir_credencial(user_id, email, senha):
        # Só se dois cadastros com o mesmo e-mail chegarem ao mesmo tempo.
        raise ErroAuth(grpc.StatusCode.ALREADY_EXISTS, "E-mail já cadastrado")
    log.ok(f"Cadastro: {nome} <{email}> -> {user_id} "
           f"(foto de {resposta.tamanho_foto_bytes // 1024} KB no Discovery)")

    # Leva o nome para o cache do Messaging já no cadastro. Se o Messaging
    # estiver fora, o nome vai para a fila e o cadastro NÃO falha: o chat
    # é outra parte do sistema e não pode impedir alguém de se cadastrar.
    await sincronizacao.sincronizar_nome(user_id, nome)
    return user_id


def entrar(email, senha):
    """Confere e-mail e senha no banco local e retorna o user_id. Não chama nenhum serviço."""
    user_id = banco.buscar_user_id(email.strip().lower(), senha)
    if user_id is None:
        log.aviso(f"Login recusado para {email}")
        raise ErroAuth(grpc.StatusCode.UNAUTHENTICATED, "E-mail ou senha incorretos")
    log.ok(f"Login: {email} -> {user_id}")
    return user_id


class ServicoAuth(auth_pb2_grpc.AuthServicer):
    """Expõe cadastrar()/entrar() via gRPC (protos/auth.proto)."""

    async def Register(self, request, context):
        """RPC unário de cadastro."""
        try:
            user_id = await cadastrar(request.email, request.senha, request.nome,
                                      request.bio, request.foto, request.extensao_foto)
        except ErroAuth as erro:
            await context.abort(erro.codigo, erro.mensagem)
        return auth_pb2.RespostaCadastro(user_id=user_id)

    async def Login(self, request, context):
        """RPC unário de login."""
        try:
            user_id = entrar(request.email, request.senha)
        except ErroAuth as erro:
            await context.abort(erro.codigo, erro.mensagem)
        return auth_pb2.RespostaLogin(user_id=user_id)


async def iniciar_servidor_grpc():
    """Sobe o servidor gRPC do Auth (com Health Check) dentro do processo do Gateway."""
    servidor = grpc.aio.server()
    auth_pb2_grpc.add_AuthServicer_to_server(ServicoAuth(), servidor)

    saude = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(saude, servidor)
    await saude.set("", health_pb2.HealthCheckResponse.SERVING)
    await saude.set("auth.Auth", health_pb2.HealthCheckResponse.SERVING)

    endereco = f"{config.ENDERECO_ESCUTA}:{config.AUTH_PORT}"
    servidor.add_insecure_port(endereco)
    await servidor.start()
    log.ok(f"Auth (gRPC) escutando em {endereco}")
    return servidor, saude
