"""
Servidor gRPC do Messaging: chat em tempo real, lista de conversas e cache de nomes.

Rodar (a partir da raiz do projeto):
    python -m messaging.servidor

Este serviço NUNCA chama o Discovery (nem nenhum outro serviço). Ele nem
sabe quais usuários existem: aceita mensagens entre qualquer par de
user_id. Por isso o chat continua funcionando mesmo com o Discovery fora.
"""

import queue
import signal
import threading
from collections import defaultdict
from concurrent import futures

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

import config
from gerado import messaging_pb2, messaging_pb2_grpc
from logs import Log
from messaging import banco

log = Log("MESSAGING")


def montar_mensagem(linha):
    """Converte uma mensagem do banco em MensagemChat, com o nome do remetente em cache."""
    return messaging_pb2.MensagemChat(
        id=linha["id"],
        de_user_id=linha["de_user_id"],
        de_nome=banco.buscar_nome(linha["de_user_id"]),
        para_user_id=linha["para_user_id"],
        texto=linha["texto"],
        enviada_em=linha["enviada_em"],
    )


class CentralDeConversas:
    """
    Guarda, em memória, quem está com cada conversa aberta neste momento.

    Cada stream de Chat aberto tem a sua própria fila (queue.Queue). Quando
    chega uma mensagem de A para B, ela é colocada:
      - na fila de todo stream de B aberto na conversa com A (B recebe);
      - na fila de todo stream de A aberto na conversa com B (A recebe a
        confirmação, já com id e horário definidos pelo servidor).
    "Todo stream" porque a mesma pessoa pode estar com o chat aberto em
    duas abas ao mesmo tempo.

    Fica só em memória: se o Messaging reiniciar, os streams caem de
    qualquer forma, e as mensagens já estão salvas no banco.
    """

    def __init__(self):
        self._trava = threading.Lock()  # várias threads mexem no dicionário
        self._filas = defaultdict(set)  # (eu, outro) -> filas dos streams abertos

    def entrar(self, eu, outro, fila):
        """Registra um stream aberto de 'eu' conversando com 'outro'."""
        with self._trava:
            self._filas[(eu, outro)].add(fila)

    def sair(self, eu, outro, fila):
        """Remove o registro quando o stream termina."""
        with self._trava:
            self._filas[(eu, outro)].discard(fila)
            if not self._filas[(eu, outro)]:
                del self._filas[(eu, outro)]

    def entregar(self, mensagem):
        """Coloca uma mensagem nova na fila de todos os streams interessados."""
        de, para = mensagem.de_user_id, mensagem.para_user_id
        with self._trava:
            interessados = list(self._filas.get((para, de), ())) + list(self._filas.get((de, para), ()))
        for fila in interessados:
            fila.put(mensagem)


class ServicoMessaging(messaging_pb2_grpc.MessagingServicer):
    """Implementação dos RPCs definidos em protos/messaging.proto."""

    def __init__(self):
        self.central = CentralDeConversas()

    # ----- UNÁRIO -----------------------------------------------------------
    def AtualizarNome(self, request, context):
        """Atualiza a cópia local do nome de um usuário (chamado pelo Gateway)."""
        novo_nome = request.novo_nome.strip()
        if not request.user_id or not novo_nome:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id e novo_nome são obrigatórios")
        banco.salvar_nome(request.user_id, novo_nome)
        log.ok(f"AtualizarNome: {request.user_id} agora é '{novo_nome}'")
        return messaging_pb2.Confirmacao(mensagem="Nome atualizado")

    # ----- BIDIRECIONAL -----------------------------------------------------
    def Chat(self, request_iterator, context):
        """
        Stream bidirecional de uma conversa entre dois usuários.

        Um stream bidirecional tem dois "sentidos" independentes rodando ao
        mesmo tempo, e precisamos das duas coisas ao mesmo tempo:
          - LER o que o cliente envia (request_iterator);
          - ESCREVER o que chega para ele (cada "yield" desta função).
        Ler do request_iterator trava até o cliente mandar algo; se só
        tivéssemos esta função, ela não conseguiria entregar mensagens da
        outra pessoa enquanto espera. Solução: uma thread auxiliar só para
        LER, enquanto esta função fica só ESCREVENDO o que aparece na fila.
        """
        # A 1ª mensagem identifica a conversa: quem sou eu e com quem falo.
        primeira = next(request_iterator, None)
        if primeira is None or not primeira.de_user_id or not primeira.para_user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "A 1ª mensagem do Chat deve ter de_user_id e para_user_id")
        eu, outro = primeira.de_user_id, primeira.para_user_id
        if eu == outro:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Não é possível abrir chat consigo mesmo")

        fila = queue.Queue()
        # Registra ANTES de ler o histórico: assim nenhuma mensagem que
        # chegue nesse meio-tempo se perde (no pior caso ela vem duplicada,
        # e o filtro por id lá embaixo descarta a repetição).
        self.central.entrar(eu, outro, fila)
        # Se o cliente desconectar (fechou a aba, caiu a rede), o gRPC chama
        # esta função; o None acorda o laço de envio para ele terminar.
        context.add_callback(lambda: fila.put(None))
        log.info(f"Chat aberto: {eu} <-> {outro}")

        try:
            ultimo_id_enviado = 0
            for linha in banco.buscar_historico(eu, outro):
                yield montar_mensagem(linha)
                ultimo_id_enviado = linha["id"]

            if primeira.texto.strip():
                self._registrar_mensagem(eu, outro, primeira.texto)

            leitor = threading.Thread(target=self._ler_envios,
                                      args=(request_iterator, eu, outro, fila), daemon=True)
            leitor.start()

            # Laço de ESCRITA: cada mensagem que aparece na fila é enviada.
            while True:
                # Espera (sem gastar CPU) até chegar algo, mas acorda a cada
                # 1s para conferir se a chamada ainda existe. Sem esse prazo,
                # num "systemctl stop" com chats abertos, esta thread podia
                # ficar esperando para sempre e o processo demorava ~20s
                # para terminar.
                try:
                    mensagem = fila.get(timeout=1)
                except queue.Empty:
                    if not context.is_active():
                        break
                    continue
                if mensagem is None:   # sinal de fim do stream
                    break
                if mensagem.id <= ultimo_id_enviado:
                    continue           # já foi enviada junto com o histórico
                yield mensagem
                ultimo_id_enviado = mensagem.id
        finally:
            # Roda sempre, inclusive se o cliente desconectar no meio.
            self.central.sair(eu, outro, fila)
            log.info(f"Chat fechado: {eu} <-> {outro}")

    def _ler_envios(self, request_iterator, eu, outro, fila):
        """Thread auxiliar do Chat: lê o que o cliente envia e distribui."""
        try:
            # Depois da 1ª mensagem, a conversa já está definida; os campos
            # de_user_id/para_user_id das seguintes são ignorados, então o
            # cliente não consegue "trocar de conversa" no meio do stream.
            for envio in request_iterator:
                if envio.texto.strip():
                    self._registrar_mensagem(eu, outro, envio.texto)
        except grpc.RpcError:
            pass  # cliente desconectou de forma abrupta; tratado no finally
        finally:
            # O cliente parou de enviar (fechou o stream): encerra também o
            # sentido servidor -> cliente.
            fila.put(None)

    def _registrar_mensagem(self, de, para, texto):
        """Salva a mensagem no banco e entrega a quem estiver com a conversa aberta."""
        linha = banco.salvar_mensagem(de, para, texto.strip())
        log.ok(f"Mensagem #{linha['id']}: {de} -> {para}: {linha['texto']!r}")
        self.central.entregar(montar_mensagem(linha))

    # ----- SERVER STREAMING -------------------------------------------------
    def ListarConversas(self, request, context):
        """Envia, uma por mensagem, as conversas do usuário (mais recente primeiro)."""
        if not request.user_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id é obrigatório")

        linhas = banco.listar_conversas(request.user_id)
        log.info(f"ListarConversas: {len(linhas)} conversa(s) para {request.user_id}")
        for linha in linhas:
            yield messaging_pb2.Conversa(
                outro_user_id=linha["outro_user_id"],
                outro_nome=linha["outro_nome"],
                ultima_mensagem=linha["ultima_mensagem"],
                ultima_em=linha["ultima_em"],
            )


def servir():
    """Sobe o servidor gRPC (Messaging + Health Check) e fica escutando."""
    banco.criar_tabelas()

    # Diferente do Discovery, aqui cada chat aberto ocupa uma thread do pool
    # durante TODO o tempo em que fica aberto. Com ~20 pessoas, cada uma com
    # uma ou duas conversas abertas, 10 threads acabariam rápido e os
    # próximos chats ficariam esperando. 100 dá folga (threads paradas
    # esperando a fila quase não gastam CPU).
    servidor = grpc.server(futures.ThreadPoolExecutor(max_workers=100))
    messaging_pb2_grpc.add_MessagingServicer_to_server(ServicoMessaging(), servidor)

    saude = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(saude, servidor)
    saude.set("", health_pb2.HealthCheckResponse.SERVING)
    saude.set("messaging.Messaging", health_pb2.HealthCheckResponse.SERVING)

    endereco = f"{config.ENDERECO_ESCUTA}:{config.MESSAGING_PORT}"
    servidor.add_insecure_port(endereco)
    servidor.start()
    log.ok(f"Messaging escutando em {endereco}")

    def desligar(*_):
        log.aviso("Desligando...")
        saude.enter_graceful_shutdown()
        servidor.stop(grace=2)

    signal.signal(signal.SIGTERM, desligar)
    try:
        servidor.wait_for_termination()
    except KeyboardInterrupt:
        desligar()


if __name__ == "__main__":
    servir()
