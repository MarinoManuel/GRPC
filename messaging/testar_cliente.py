"""
Cliente de teste do Messaging: testa o serviço SOZINHO, sem Gateway.

Rodar (com o servidor já no ar):
    python -m messaging.testar_cliente

Simula duas pessoas (A e B) conversando ao mesmo tempo, cada uma com o seu
próprio stream bidirecional, e mostra quem recebeu o quê.
Usa o endereço de config.py (MESSAGING_HOST/PORT).
"""

import queue
import threading
import time
import uuid

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

import config
from gerado import messaging_pb2 as pb
from gerado import messaging_pb2_grpc
from logs import Log

log = Log("TESTE")


class ParticipanteChat:
    """Abre um stream de Chat e registra tudo o que recebe, numa thread própria."""

    def __init__(self, stub, rotulo, eu, outro):
        self.rotulo = rotulo
        self.textos = queue.Queue()
        self.recebidas = []

        def envios():
            yield pb.EnvioChat(de_user_id=eu, para_user_id=outro)
            while (texto := self.textos.get()) is not None:
                yield pb.EnvioChat(de_user_id=eu, para_user_id=outro, texto=texto)

        self.respostas = stub.Chat(envios(), timeout=30)
        self.thread = threading.Thread(target=self._receber, daemon=True)
        self.thread.start()

    def _receber(self):
        for m in self.respostas:
            self.recebidas.append(m)
            log.info(f"  {self.rotulo} recebeu #{m.id} de {m.de_nome!r}: {m.texto!r}")

    def enviar(self, texto):
        """Envia uma mensagem pelo stream (não espera resposta)."""
        self.textos.put(texto)

    def fechar(self):
        """Fecha o lado do cliente e espera o servidor encerrar o stream."""
        self.textos.put(None)
        self.thread.join(timeout=5)


def esperar_erro(descricao, chamada):
    """Executa uma chamada que DEVE falhar e mostra o status gRPC recebido."""
    try:
        chamada()
        log.erro(f"{descricao}: deveria ter falhado, mas não falhou!")
    except grpc.RpcError as erro:
        log.ok(f"{descricao} -> {erro.code().name}: {erro.details()}")


def main():
    """Roda todos os RPCs do Messaging em sequência, incluindo casos de erro."""
    endereco = config.endereco_messaging()
    t = config.TIMEOUT_SEGUNDOS
    canal = grpc.insecure_channel(endereco)
    stub = messaging_pb2_grpc.MessagingStub(canal)

    # 1) Health Check -------------------------------------------------------
    log.info(f"Conectando no Messaging em {endereco}...")
    try:
        resposta = health_pb2_grpc.HealthStub(canal).Check(
            health_pb2.HealthCheckRequest(service="messaging.Messaging"), timeout=t)
        log.ok(f"Health Check: {health_pb2.HealthCheckResponse.ServingStatus.Name(resposta.status)}")
    except grpc.RpcError as erro:
        log.erro(f"Messaging inacessível: {erro.code().name} — {erro.details()}")
        return

    # IDs novos a cada execução, para os testes não se misturarem.
    id_a = f"teste-a-{uuid.uuid4().hex[:6]}"
    id_b = f"teste-b-{uuid.uuid4().hex[:6]}"

    # 2) AtualizarNome (unário) — só para A. B fica sem nome em cache --------
    stub.AtualizarNome(pb.PedidoAtualizarNome(user_id=id_a, novo_nome="Alice"), timeout=t)
    log.ok(f"AtualizarNome: {id_a} = 'Alice' ({id_b} fica sem nome, deve aparecer 'Usuário')")

    # 3) Chat (bidirecional) — A e B com a conversa aberta ao mesmo tempo ----
    log.info("Chat: A e B abrem a conversa e trocam mensagens...")
    a = ParticipanteChat(stub, "A", id_a, id_b)
    b = ParticipanteChat(stub, "B", id_b, id_a)
    time.sleep(0.3)  # dá tempo dos dois streams se registrarem no servidor
    for remetente, texto in [(a, "Oi, tudo bem?"), (b, "Tudo ótimo! E você?"), (a, "Também!")]:
        remetente.enviar(texto)
        time.sleep(0.3)  # só para a saída ficar em ordem de leitura
    a.fechar()
    b.fechar()
    log.ok(f"Chat: A recebeu {len(a.recebidas)} e B recebeu {len(b.recebidas)} mensagens "
           f"(esperado 3 e 3: cada um recebe as do outro e a confirmação das próprias)")

    # 4) Reabrir o chat: o histórico deve vir logo no início -----------------
    log.info("Chat: B reabre a conversa (deve receber o histórico)...")
    b2 = ParticipanteChat(stub, "B", id_b, id_a)
    time.sleep(0.5)
    b2.fechar()
    log.ok(f"Histórico: {len(b2.recebidas)} mensagens recebidas ao reabrir")

    # 5) ListarConversas (server streaming) ----------------------------------
    for conversa in stub.ListarConversas(pb.PedidoListarConversas(user_id=id_a), timeout=t):
        log.ok(f"ListarConversas(A): com {conversa.outro_nome!r} — "
               f"última: {conversa.ultima_mensagem!r} em {conversa.ultima_em}")

    # O nome de B chega depois (como faria a fila de sincronização do Gateway)
    stub.AtualizarNome(pb.PedidoAtualizarNome(user_id=id_b, novo_nome="Bruno"), timeout=t)
    for conversa in stub.ListarConversas(pb.PedidoListarConversas(user_id=id_a), timeout=t):
        log.ok(f"ListarConversas(A) após AtualizarNome(B): agora aparece {conversa.outro_nome!r}")

    # 6) Casos de erro -------------------------------------------------------
    log.info("Testando erros (todos devem falhar com o código indicado):")
    esperar_erro("AtualizarNome com nome vazio",
                 lambda: stub.AtualizarNome(pb.PedidoAtualizarNome(user_id=id_a, novo_nome="  "), timeout=t))
    esperar_erro("Chat sem identificar a conversa",
                 lambda: list(stub.Chat(iter([pb.EnvioChat(texto="oi")]), timeout=t)))
    esperar_erro("Chat consigo mesmo",
                 lambda: list(stub.Chat(iter([pb.EnvioChat(de_user_id=id_a, para_user_id=id_a)]), timeout=t)))
    esperar_erro("ListarConversas sem user_id",
                 lambda: list(stub.ListarConversas(pb.PedidoListarConversas(), timeout=t)))

    canal.close()
    log.ok("Todos os testes do Messaging concluídos")


if __name__ == "__main__":
    main()
