"""
Configuração central de endereços e portas do projeto.

Este é o ÚNICO lugar onde aparecem endereços de rede. Nenhum outro arquivo
do projeto deve ter "localhost", IP ou porta escritos diretamente.

Como funciona:
  - O Gateway (no seu PC) lê DISCOVERY_HOST/PORT e MESSAGING_HOST/PORT para
    saber ONDE procurar cada serviço. Para trocar um serviço de máquina
    (ex.: rodar o Messaging num PC da sala em vez da nuvem), basta editar
    o HOST correspondente aqui, no PC do Gateway. Nada mais muda.
  - Cada serviço usa apenas a sua própria PORTA daqui, e sempre escuta em
    0.0.0.0 (todas as interfaces de rede). Assim o serviço não precisa
    saber o próprio IP público: quem precisa saber o endereço é quem liga
    para ele (o Gateway), não quem atende.
"""

# ---------------------------------------------------------------------------
# Onde o GATEWAY procura cada serviço (edite só estas linhas para mudar
# um serviço de máquina).
# ---------------------------------------------------------------------------

# Enquanto testamos tudo no mesmo PC, "localhost". No deploy (módulos 3/4),
# troque pelos IPs dos servidores:
#   Discovery -> VPS Hostinger (alias "vps"): 82.112.240.107
#   Messaging -> Oracle Cloud:                129.151.186.241
DISCOVERY_HOST = "82.112.240.107"    # VPS Hostinger  (local: "localhost")
DISCOVERY_PORT = 50052

MESSAGING_HOST = "129.151.186.241"   # Oracle Cloud   (local: "localhost")
MESSAGING_PORT = 50053

# O Auth roda no mesmo processo do Gateway (seu PC). Ele também expõe uma
# porta gRPC, para que o painel de monitoramento consiga fazer Health Check
# nele exatamente como faz nos outros dois serviços.
AUTH_HOST = "localhost"
AUTH_PORT = 50051

# Porta HTTP (REST/WebSocket) onde o Gateway atende o futuro frontend.
GATEWAY_PORT = 8000

# ---------------------------------------------------------------------------
# Onde cada serviço ESCUTA. "0.0.0.0" = aceitar conexões vindas de qualquer
# interface de rede (localhost, rede local e internet).
# ---------------------------------------------------------------------------
ENDERECO_ESCUTA = "0.0.0.0"

# ---------------------------------------------------------------------------
# Deadline (timeout) padrão das chamadas gRPC feitas pelo Gateway.
# Nenhuma chamada pode esperar para sempre: se o outro lado não responder
# nesse tempo, o gRPC cancela e devolve DEADLINE_EXCEEDED, e o Gateway
# segue a vida (degradação graciosa).
# ---------------------------------------------------------------------------
TIMEOUT_SEGUNDOS = 3.0

# Deadline do Health Check (letreiro do site e painel). Em localhost ele
# responde em ~1 ms, mas pela internet deste PC já medimos até 2,5 s.
# Estourar o prazo (DEADLINE_EXCEEDED) é mostrado como "LENTO", não como
# "fora do ar": fora do ar é quando ninguém atende (UNAVAILABLE).
TIMEOUT_HEALTH_SEGUNDOS = 5.0

# Chamadas que transportam fotos (upload no cadastro, feed, perfil com foto)
# movem centenas de KB. Numa conexão lenta (medimos 15–60 KB/s neste PC),
# isso pode levar bem mais que 3s, então têm um prazo maior. Continua sendo
# um limite: nunca esperar para sempre.
TIMEOUT_STREAM_SEGUNDOS = 30.0

# O stream de chat fica aberto enquanto a pessoa está na conversa. Ele
# também tem prazo (1 hora); ao expirar, o frontend simplesmente reabre.
DURACAO_MAXIMA_CHAT_SEGUNDOS = 3600


def endereco_discovery():
    """Retorna "host:porta" do Discovery, no formato que o gRPC espera."""
    return f"{DISCOVERY_HOST}:{DISCOVERY_PORT}"


def endereco_messaging():
    """Retorna "host:porta" do Messaging, no formato que o gRPC espera."""
    return f"{MESSAGING_HOST}:{MESSAGING_PORT}"


def endereco_auth():
    """Retorna "host:porta" do Auth, no formato que o gRPC espera."""
    return f"{AUTH_HOST}:{AUTH_PORT}"


if __name__ == "__main__":
    # Rodar "python config.py" mostra a configuração atual — útil para
    # conferir rapidamente para onde o Gateway vai apontar.
    print("Configuração atual:")
    print(f"  Auth      -> {endereco_auth()}")
    print(f"  Discovery -> {endereco_discovery()}")
    print(f"  Messaging -> {endereco_messaging()}")
    print(f"  Gateway HTTP na porta {GATEWAY_PORT}")
    print(f"  Serviços escutam em {ENDERECO_ESCUTA}")
    print(f"  Timeout das chamadas gRPC: {TIMEOUT_SEGUNDOS}s")
