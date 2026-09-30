"""
Chat interativo no terminal: demonstra o streaming bidirecional ao vivo.

Abra DOIS terminais (com o servidor do Messaging no ar):
    python -m messaging.chat_terminal ana bruno "Ana"
    python -m messaging.chat_terminal bruno ana "Bruno"

Argumentos: <meu_id> <id_da_outra_pessoa> [meu_nome_opcional]
Digite e aperte Enter para enviar; /sair (ou Ctrl+C) para sair.
Usa o endereço de config.py (MESSAGING_HOST/PORT).
"""

import queue
import sys
import threading
from datetime import datetime

import grpc

import config
from gerado import messaging_pb2 as pb
from gerado import messaging_pb2_grpc
from logs import Log

log = Log("CHAT")


def main():
    """Abre o stream de Chat e fica enviando o que for digitado."""
    if len(sys.argv) < 3:
        print(__doc__)
        return
    eu, outro = sys.argv[1], sys.argv[2]

    canal = grpc.insecure_channel(config.endereco_messaging())
    stub = messaging_pb2_grpc.MessagingStub(canal)

    if len(sys.argv) > 3:
        stub.AtualizarNome(pb.PedidoAtualizarNome(user_id=eu, novo_nome=sys.argv[3]),
                           timeout=config.TIMEOUT_SEGUNDOS)

    # O que for digitado vai para esta fila; o gerador abaixo tira da fila
    # e entrega ao gRPC, que envia pelo stream.
    textos = queue.Queue()

    def envios():
        yield pb.EnvioChat(de_user_id=eu, para_user_id=outro)  # abre a conversa
        while True:
            texto = textos.get()
            if texto is None:
                return  # fim do gerador = cliente fecha o seu lado do stream
            yield pb.EnvioChat(de_user_id=eu, para_user_id=outro, texto=texto)

    # Sem deadline aqui, de propósito: é uma ferramenta de demonstração e a
    # conversa pode durar o tempo que você quiser.
    respostas = stub.Chat(envios())
    saindo = threading.Event()  # diferencia "eu saí" de "o servidor caiu"

    def receber():
        # Roda numa thread separada: enquanto o terminal espera você digitar,
        # esta thread continua recebendo e mostrando as mensagens que chegam.
        try:
            for m in respostas:
                quem = "você" if m.de_user_id == eu else m.de_nome
                # O servidor manda em UTC; astimezone() converte para o fuso deste PC.
                hora = datetime.fromisoformat(m.enviada_em).astimezone().strftime("%H:%M")
                print(f"  [{hora}] {quem}: {m.texto}", flush=True)
            if not saindo.is_set():
                log.aviso("O servidor encerrou a conversa. Aperte Enter para sair.")
        except grpc.RpcError as erro:
            if not saindo.is_set():
                log.erro(f"Conexão com o Messaging perdida: {erro.code().name}. Aperte Enter para sair.")

    receptor = threading.Thread(target=receber, daemon=True)
    receptor.start()
    log.ok(f"Conversa aberta: {eu} -> {outro}. Digite /sair para sair.")

    try:
        while receptor.is_alive():
            texto = input()
            if texto.strip() == "/sair":
                break
            textos.put(texto)
    except (KeyboardInterrupt, EOFError):
        pass
    saindo.set()
    textos.put(None)
    receptor.join(timeout=2)
    canal.close()


if __name__ == "__main__":
    main()
