"""
Painel de saúde: mostra ao vivo, no terminal, se cada serviço está no ar.

Rodar (em um terminal separado, durante a demonstração):
    python -m painel.painel

A cada 2 segundos faz o Health Check padrão do gRPC (grpc.health.v1) no
Auth, no Discovery e no Messaging, e consulta o /api/status do Gateway para
mostrar quantos nomes aguardam na fila de sincronização. Embaixo, guarda
um histórico das mudanças de estado ("Messaging: SERVING -> FORA DO AR").

O painel é um programa à parte: não faz parte de nenhum serviço e não
altera nada. Só observa, como uma ferramenta de monitoramento real faria.
"""

import json
import time
import urllib.request
from collections import deque
from datetime import datetime

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

import config
from logs import AMARELO, CINZA, NEGRITO, RESET, VERDE, VERMELHO

INTERVALO_SEGUNDOS = 2

SERVICOS = [
    ("Auth", config.endereco_auth(), "auth.Auth"),
    ("Discovery", config.endereco_discovery(), "discovery.Discovery"),
    ("Messaging", config.endereco_messaging(), "messaging.Messaging"),
]

# Mesma ideia do Gateway: limitar a espera entre tentativas de reconexão,
# para o painel perceber em poucos segundos quando um serviço volta.
OPCOES_CANAL = [("grpc.initial_reconnect_backoff_ms", 1000),
                ("grpc.max_reconnect_backoff_ms", 3000)]


# Estado atual da conexão de cada canal (READY, CONNECTING...), atualizado
# pelo próprio gRPC através de channel.subscribe() (ver main()).
estado_conexao = {}


def checar_grpc(stub, nome, nome_servico):
    """Faz um Health Check e devolve (estado, milissegundos)."""
    inicio = time.perf_counter()
    try:
        resposta = stub.Check(health_pb2.HealthCheckRequest(service=nome_servico),
                              timeout=config.TIMEOUT_HEALTH_SEGUNDOS)
        estado = health_pb2.HealthCheckResponse.ServingStatus.Name(resposta.status)
    except grpc.RpcError as erro:
        # Prazo estourado é ambíguo pela internet: rede lenta OU serviço parado
        # cujo "conexão recusada" nunca chegou. Desempate pela conexão: se ela
        # continua READY, o serviço está lá e só demorou (amarelo); senão, não
        # há ninguém do outro lado (vermelho).
        if erro.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            if estado_conexao.get(nome) == grpc.ChannelConnectivity.READY:
                estado = "LENTO (rede)"
            else:
                estado = "FORA DO AR (SEM CONEXÃO)"
        else:
            estado = f"FORA DO AR ({erro.code().name})"
    return estado, (time.perf_counter() - inicio) * 1000


def checar_gateway():
    """Consulta o /api/status do Gateway; devolve o JSON ou None se não respondeu."""
    try:
        url = f"http://127.0.0.1:{config.GATEWAY_PORT}/api/status"
        # /api/status faz Health Checks com até TIMEOUT_HEALTH_SEGUNDOS: esperar um pouco mais que isso.
        with urllib.request.urlopen(url, timeout=config.TIMEOUT_HEALTH_SEGUNDOS + 2) as resposta:
            return json.loads(resposta.read())
    except Exception:
        return None


def pintar(estado):
    """Verde para SERVING, amarelo para NOT_SERVING (desligando) ou LENTO, vermelho para fora do ar."""
    if estado in ("SERVING", "NO AR"):
        return f"{VERDE}● {estado}{RESET}"
    if estado.startswith("FORA"):
        return f"{VERMELHO}● {estado}{RESET}"
    return f"{AMARELO}● {estado}{RESET}"


def main():
    """Laço principal: checa, desenha a tela, espera, repete."""
    stubs = {}
    for nome, endereco, _ in SERVICOS:
        canal = grpc.insecure_channel(endereco, options=OPCOES_CANAL)
        # O gRPC chama esta função a cada mudança de estado da conexão.
        canal.subscribe(lambda estado, n=nome: estado_conexao.__setitem__(n, estado), try_to_connect=True)
        stubs[nome] = health_pb2_grpc.HealthStub(canal)
    ultimo_estado = {}
    historico = deque(maxlen=10)

    try:
        while True:
            linhas = []
            for nome, endereco, nome_grpc in SERVICOS:
                estado, ms = checar_grpc(stubs[nome], nome, nome_grpc)
                linhas.append(f"  {nome:<10} {endereco:<24} {pintar(estado):<40} {CINZA}{ms:5.0f} ms{RESET}")
                if nome in ultimo_estado and ultimo_estado[nome] != estado:
                    historico.append(f"{datetime.now():%H:%M:%S}  {nome}: {ultimo_estado[nome]} -> {estado}")
                ultimo_estado[nome] = estado

            gateway = checar_gateway()
            if gateway is None:
                estado_gw, fila = "FORA DO AR", "-"
            else:
                estado_gw = "NO AR"
                pendentes = gateway["nomes_pendentes"]
                cor = AMARELO if pendentes else VERDE
                fila = f"{cor}{pendentes} nome(s) pendente(s){RESET}"
            if "Gateway" in ultimo_estado and ultimo_estado["Gateway"] != estado_gw:
                historico.append(f"{datetime.now():%H:%M:%S}  Gateway: {ultimo_estado['Gateway']} -> {estado_gw}")
            ultimo_estado["Gateway"] = estado_gw

            # \033[2J limpa a tela e \033[H volta o cursor ao topo: redesenha no lugar.
            print("\033[2J\033[H", end="")
            print(f"{NEGRITO}  PAINEL DE SAÚDE — {datetime.now():%H:%M:%S}{RESET}"
                  f"   {CINZA}(a cada {INTERVALO_SEGUNDOS}s, Ctrl+C para sair){RESET}\n")
            print("\n".join(linhas))
            print(f"  {'Gateway':<10} {'http://127.0.0.1:' + str(config.GATEWAY_PORT):<24} "
                  f"{pintar(estado_gw):<40}")
            print(f"\n  Fila de sincronização de nomes: {fila}")
            print(f"\n{NEGRITO}  Mudanças de estado:{RESET}")
            print("\n".join(f"  {evento}" for evento in historico) or f"  {CINZA}(nenhuma ainda){RESET}")

            time.sleep(INTERVALO_SEGUNDOS)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
