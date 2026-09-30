"""
Conexões (canais gRPC) do Gateway com o Discovery e o Messaging.

Um canal gRPC é uma conexão de longa duração que pode ser reutilizada por
milhares de chamadas. Por isso cada canal é criado UMA vez, quando o
Gateway sobe, e não a cada requisição.

Usamos a versão assíncrona do gRPC (grpc.aio) porque o FastAPI é
assíncrono: enquanto uma chamada espera resposta da rede, o Gateway
continua atendendo outras requisições no mesmo processo.
"""

import grpc
from grpc_health.v1 import health_pb2_grpc

import config
from gerado import discovery_pb2_grpc, messaging_pb2_grpc

# Quando um serviço cai, o canal gRPC tenta reconectar sozinho, esperando
# cada vez mais entre as tentativas; por padrão, esse intervalo pode chegar
# a 2 MINUTOS. Isso é a reconexão automática do gRPC: ela cuida só da
# CONEXÃO, e não reenvia nenhuma chamada que falhou (para isso existe a
# nossa fila de nomes). Limitamos o intervalo a 5s para que, quando o
# serviço voltar, o Gateway perceba rápido. Bom para a demonstração ao vivo.
OPCOES_CANAL = [
    ("grpc.initial_reconnect_backoff_ms", 1000),
    ("grpc.max_reconnect_backoff_ms", 5000),
]

# Preenchidos por abrir(). Os outros módulos usam "clientes.discovery" etc.
discovery = None
messaging = None
saude_discovery = None
saude_messaging = None
canal_discovery = None   # os canais também ficam acessíveis: o /api/status
canal_messaging = None   # consulta o estado da conexão de cada um
_canais = []


def abrir():
    """Cria os canais e os stubs. Precisa ser chamado com o loop assíncrono rodando."""
    global discovery, messaging, saude_discovery, saude_messaging, canal_discovery, canal_messaging
    canal_discovery = grpc.aio.insecure_channel(config.endereco_discovery(), options=OPCOES_CANAL)
    canal_messaging = grpc.aio.insecure_channel(config.endereco_messaging(), options=OPCOES_CANAL)
    _canais.extend([canal_discovery, canal_messaging])

    # Cada serviço tem o seu canal separado: se um cai, o outro canal
    # nem percebe. Isolamento de falha começa aqui.
    discovery = discovery_pb2_grpc.DiscoveryStub(canal_discovery)
    messaging = messaging_pb2_grpc.MessagingStub(canal_messaging)
    saude_discovery = health_pb2_grpc.HealthStub(canal_discovery)
    saude_messaging = health_pb2_grpc.HealthStub(canal_messaging)


async def fechar():
    """Fecha os canais ao desligar o Gateway."""
    for canal in _canais:
        await canal.close()
