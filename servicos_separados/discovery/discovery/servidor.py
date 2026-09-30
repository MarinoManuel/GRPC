"""
Servidor gRPC do Discovery: perfis, feed e likes.

Rodar (a partir da raiz do projeto):
    python -m discovery.servidor

Este serviço NUNCA chama outro serviço. Ele só responde a quem o chama
(o Gateway). Por isso pode cair ou voltar sem afetar o Messaging.
"""

import signal
from concurrent import futures

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

import config
from discovery import banco
from gerado import discovery_pb2, discovery_pb2_grpc
from logs import Log

log = Log("DISCOVERY")

# Fotos enviadas pelos usuários ficam separadas das fotos fixas do seed
# (discovery/fotos/), para não misturar "dados" com "arquivos do projeto".
PASTA_FOTOS_USUARIOS = banco.PASTA_SERVICO / "fotos_usuarios"
# 3 MB: no GetFeed cada Perfil viaja INTEIRO (com a foto) numa só mensagem,
# e o gRPC por padrão recusa mensagens acima de 4 MB. Mantendo a foto
# abaixo disso, nenhum cliente precisa mudar configuração de tamanho.
TAMANHO_MAXIMO_FOTO = 3 * 1024 * 1024

TIPOS_DE_FOTO = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def montar_perfil(linha):
    """Converte uma linha do banco numa mensagem Perfil, lendo a foto do disco na hora."""
    caminho = banco.PASTA_SERVICO / linha["caminho_foto"]
    try:
        foto = caminho.read_bytes()
    except FileNotFoundError:
        # Um arquivo sumido não deve derrubar o feed inteiro: envia o perfil
        # sem foto e registra o problema.
        log.aviso(f"Foto não encontrada: {linha['caminho_foto']}")
        foto = b""
    extensao = caminho.suffix.lstrip(".").lower()
    return discovery_pb2.Perfil(
        user_id=linha["user_id"],
        nome=linha["nome"],
        bio=linha["bio"],
        foto=foto,
        tipo_foto=TIPOS_DE_FOTO.get(extensao, "application/octet-stream"),
    )


class ServicoDiscovery(discovery_pb2_grpc.DiscoveryServicer):
    """Implementação dos RPCs definidos em protos/discovery.proto.

    Observação: context.abort(codigo, mensagem) LANÇA uma exceção que
    encerra a chamada e devolve ao cliente aquele status de erro, então
    nada depois dele é executado (não precisa de "return").
    """

    # ----- CLIENT STREAMING -------------------------------------------------
    def CreateProfile(self, request_iterator, context):
        """Recebe os dados do perfil e depois a foto em pedaços; salva tudo."""
        # request_iterator entrega as mensagens do cliente conforme elas
        # chegam pela rede. A 1ª precisa ser os dados do perfil.
        primeira = next(request_iterator, None)
        if primeira is None or primeira.WhichOneof("conteudo") != "dados":
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "A primeira mensagem do stream deve conter os dados do perfil")

        dados = primeira.dados
        extensao = dados.extensao_foto.lower().lstrip(".")
        if not dados.user_id or not dados.nome.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id e nome são obrigatórios")
        if extensao not in TIPOS_DE_FOTO:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          f"Extensão de foto inválida: '{dados.extensao_foto}'")
        if banco.perfil_existe(dados.user_id):
            context.abort(grpc.StatusCode.ALREADY_EXISTS, f"Perfil {dados.user_id} já existe")

        # Remonta a foto juntando os pedaços na ordem em que chegam.
        # (O gRPC garante a ordem das mensagens dentro de um mesmo stream.)
        foto = bytearray()
        pedacos = 0
        for mensagem in request_iterator:
            if mensagem.WhichOneof("conteudo") != "pedaco_foto":
                context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                              "Depois dos dados, o stream só pode conter pedaços da foto")
            foto.extend(mensagem.pedaco_foto)
            pedacos += 1
            if len(foto) > TAMANHO_MAXIMO_FOTO:
                context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Foto maior que 3 MB")
        if not foto:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "A foto é obrigatória")

        # Grava o arquivo ANTES da linha no banco: assim nunca existe um
        # perfil no banco apontando para uma foto que ainda não existe.
        caminho_relativo = f"fotos_usuarios/{dados.user_id}.{extensao}"
        PASTA_FOTOS_USUARIOS.mkdir(exist_ok=True)
        (banco.PASTA_SERVICO / caminho_relativo).write_bytes(foto)

        if not banco.inserir_perfil(dados.user_id, dados.nome.strip(), dados.bio, caminho_relativo):
            # Só acontece se duas chamadas com o mesmo id chegarem juntas.
            context.abort(grpc.StatusCode.ALREADY_EXISTS, f"Perfil {dados.user_id} já existe")

        log.ok(f"CreateProfile: {dados.nome} ({dados.user_id}) — "
               f"foto de {len(foto) // 1024} KB recebida em {pedacos} pedaços")
        return discovery_pb2.PerfilCriado(user_id=dados.user_id, tamanho_foto_bytes=len(foto))

    # ----- UNÁRIO -----------------------------------------------------------
    def UpdateProfile(self, request, context):
        """Atualiza nome e/ou bio. Só mexe nos campos que vieram preenchidos."""
        if not request.user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id é obrigatório")
        # HasField só funciona porque os campos são "optional" no .proto.
        if not request.HasField("nome") and not request.HasField("bio"):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Informe nome e/ou bio para atualizar")

        nome = request.nome.strip() if request.HasField("nome") else None
        bio = request.bio if request.HasField("bio") else None
        if nome == "":
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "O nome não pode ficar vazio")

        if not banco.atualizar_perfil(request.user_id, nome=nome, bio=bio):
            context.abort(grpc.StatusCode.NOT_FOUND, f"Perfil {request.user_id} não existe")

        log.ok(f"UpdateProfile: {request.user_id} (nome={nome!r}, bio={bio!r})")
        return discovery_pb2.Confirmacao(mensagem="Perfil atualizado")

    # ----- UNÁRIO -----------------------------------------------------------
    def GetProfile(self, request, context):
        """Devolve um único perfil, com a foto."""
        if not request.user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id é obrigatório")
        linha = banco.buscar_perfil(request.user_id)
        if linha is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"Perfil {request.user_id} não existe")
        return montar_perfil(linha)

    # ----- SERVER STREAMING -------------------------------------------------
    def GetFeed(self, request, context):
        """Envia, um por mensagem, os perfis que o usuário ainda não avaliou."""
        if not request.user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id é obrigatório")

        log.info(f"GetFeed: iniciando para {request.user_id}")
        enviados = 0
        ultimo_rowid = 0
        # Busca do banco de 5 em 5 (economiza consultas), mas entrega ao
        # cliente um perfil por vez: cada "yield" vira uma mensagem no stream.
        # Como é um gerador, só um lote fica na memória de cada vez, mesmo
        # que existam milhares de perfis.
        while True:
            lote = banco.buscar_lote_feed(request.user_id, ultimo_rowid, request.incluir_avaliados)
            if not lote:
                break
            for linha in lote:
                yield montar_perfil(linha)
                enviados += 1
                ultimo_rowid = linha["rowid"]
        log.ok(f"GetFeed: {enviados} perfis enviados para {request.user_id}")

    # ----- UNÁRIOS ----------------------------------------------------------
    def Like(self, request, context):
        """Registra que de_user_id curtiu para_user_id. Não chama nenhum outro serviço."""
        return self._avaliar(request, context, "like")

    def Pass(self, request, context):
        """Registra que de_user_id passou para_user_id (some do feed dele)."""
        return self._avaliar(request, context, "pass")

    def _avaliar(self, request, context, tipo):
        """Lógica comum de Like e Pass: valida e grava a avaliação."""
        if not request.de_user_id or not request.para_user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "de_user_id e para_user_id são obrigatórios")
        if request.de_user_id == request.para_user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Não é possível avaliar a si mesmo")
        for user_id in (request.de_user_id, request.para_user_id):
            if not banco.perfil_existe(user_id):
                context.abort(grpc.StatusCode.NOT_FOUND, f"Perfil {user_id} não existe")

        banco.registrar_avaliacao(request.de_user_id, request.para_user_id, tipo)
        log.ok(f"{tipo.capitalize()}: {request.de_user_id} -> {request.para_user_id}")
        return discovery_pb2.Confirmacao(mensagem=f"{tipo} registrado")

    # ----- SERVER STREAMING -------------------------------------------------
    def QuemMeCurtiu(self, request, context):
        """Envia, um por mensagem, os perfis de quem curtiu o usuário."""
        if not request.user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id é obrigatório")

        linhas = banco.buscar_quem_curtiu(request.user_id)
        log.info(f"QuemMeCurtiu: {len(linhas)} curtida(s) para {request.user_id}")
        for linha in linhas:
            yield montar_perfil(linha)


def servir():
    """Sobe o servidor gRPC (Discovery + Health Check) e fica escutando."""
    banco.criar_tabelas()

    # Cada chamada em andamento ocupa uma thread do pool. 10 é folga de
    # sobra para ~20 pessoas, já que as chamadas do Discovery são curtas.
    servidor = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    discovery_pb2_grpc.add_DiscoveryServicer_to_server(ServicoDiscovery(), servidor)

    # Health Check padrão do gRPC (grpc.health.v1). Qualquer cliente gRPC
    # pode perguntar "você está SERVING?" sem conhecer o discovery.proto.
    # "" = saúde do servidor como um todo; o outro nome = saúde deste serviço.
    saude = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(saude, servidor)
    saude.set("", health_pb2.HealthCheckResponse.SERVING)
    saude.set("discovery.Discovery", health_pb2.HealthCheckResponse.SERVING)

    endereco = f"{config.ENDERECO_ESCUTA}:{config.DISCOVERY_PORT}"
    servidor.add_insecure_port(endereco)
    servidor.start()
    log.ok(f"Discovery escutando em {endereco}")

    def desligar(*_):
        # Avisa os clientes de Health Check que está saindo (NOT_SERVING) e
        # dá 2s para as chamadas em andamento terminarem.
        log.aviso("Desligando...")
        saude.enter_graceful_shutdown()
        servidor.stop(grace=2)

    # SIGTERM é o sinal que o systemd envia no "systemctl stop".
    signal.signal(signal.SIGTERM, desligar)
    try:
        servidor.wait_for_termination()
    except KeyboardInterrupt:  # Ctrl+C no terminal
        desligar()


if __name__ == "__main__":
    servir()
