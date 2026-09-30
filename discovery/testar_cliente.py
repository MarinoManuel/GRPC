"""
Cliente de teste do Discovery: testa o serviço SOZINHO, sem Gateway.

Rodar (com o servidor já no ar):
    python -m discovery.testar_cliente

Usa o endereço de config.py. Para testar o Discovery já publicado na VPS,
basta mudar DISCOVERY_HOST lá e rodar este mesmo script.
"""

import time
import uuid

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

import config
from discovery.banco import PASTA_SERVICO
from gerado import discovery_pb2 as pb
from gerado import discovery_pb2_grpc
from logs import Log

log = Log("TESTE")
TAMANHO_PEDACO = 32 * 1024  # 32 KB por mensagem do stream de upload


def gerar_pedacos(user_id, nome, bio, foto, extensao):
    """Gerador das mensagens do CreateProfile: 1º os dados, depois a foto fatiada."""
    yield pb.PedacoCadastro(dados=pb.DadosPerfil(
        user_id=user_id, nome=nome, bio=bio, extensao_foto=extensao))
    for inicio in range(0, len(foto), TAMANHO_PEDACO):
        yield pb.PedacoCadastro(pedaco_foto=foto[inicio:inicio + TAMANHO_PEDACO])


def esperar_erro(descricao, chamada):
    """Executa uma chamada que DEVE falhar e mostra o status gRPC recebido."""
    try:
        chamada()
        log.erro(f"{descricao}: deveria ter falhado, mas não falhou!")
    except grpc.RpcError as erro:
        log.ok(f"{descricao} -> {erro.code().name}: {erro.details()}")


def main():
    """Roda todos os RPCs do Discovery em sequência, incluindo casos de erro."""
    endereco = config.endereco_discovery()
    t = config.TIMEOUT_SEGUNDOS
    canal = grpc.insecure_channel(endereco)
    stub = discovery_pb2_grpc.DiscoveryStub(canal)

    # 1) Health Check -------------------------------------------------------
    log.info(f"Conectando no Discovery em {endereco}...")
    try:
        resposta = health_pb2_grpc.HealthStub(canal).Check(
            health_pb2.HealthCheckRequest(service="discovery.Discovery"), timeout=t)
        log.ok(f"Health Check: {health_pb2.HealthCheckResponse.ServingStatus.Name(resposta.status)}")
    except grpc.RpcError as erro:
        log.erro(f"Discovery inacessível: {erro.code().name} — {erro.details()}")
        return

    # 2) CreateProfile (client streaming) -----------------------------------
    meu_id = str(uuid.uuid4())
    foto = (PASTA_SERVICO / "fotos" / "mulher-3.jpg").read_bytes()
    resposta = stub.CreateProfile(
        gerar_pedacos(meu_id, "Usuário de Teste", "Criado pelo script de teste", foto, "jpg"),
        timeout=t)
    log.ok(f"CreateProfile: {resposta.user_id} — servidor confirmou "
           f"{resposta.tamanho_foto_bytes} bytes (enviamos {len(foto)})")

    # 3) UpdateProfile (unário) — muda só a bio -----------------------------
    stub.UpdateProfile(pb.PedidoAtualizarPerfil(user_id=meu_id, bio="Bio editada!"), timeout=t)
    log.ok("UpdateProfile: bio alterada (nome mantido)")

    # 3b) GetProfile (unário) -----------------------------------------------
    perfil = stub.GetProfile(pb.PedidoPerfil(user_id=meu_id), timeout=t)
    log.ok(f"GetProfile: {perfil.nome!r}, bio {perfil.bio!r}, foto de {len(perfil.foto) // 1024} KB")

    # 4) GetFeed (server streaming) -----------------------------------------
    # O "for" recebe cada perfil assim que ele chega — não espera o fim.
    log.info("GetFeed: recebendo perfis um a um...")
    inicio = time.perf_counter()
    feed = []
    for perfil in stub.GetFeed(pb.PedidoFeed(user_id=meu_id), timeout=t):
        ms = (time.perf_counter() - inicio) * 1000
        log.info(f"  +{ms:6.1f} ms  {perfil.nome:<18} {len(perfil.foto) // 1024:>4} KB "
                 f"{perfil.tipo_foto}  ({perfil.user_id})")
        feed.append(perfil)
    log.ok(f"GetFeed: {len(feed)} perfis recebidos")

    # 5) Like e Pass (unários) ----------------------------------------------
    stub.Like(pb.PedidoAvaliacao(de_user_id=meu_id, para_user_id="seed-1"), timeout=t)
    log.ok("Like: teste -> seed-1 (Ana)")
    stub.Pass(pb.PedidoAvaliacao(de_user_id=meu_id, para_user_id="seed-2"), timeout=t)
    log.ok("Pass: teste -> seed-2 (Beatriz)")

    restantes = list(stub.GetFeed(pb.PedidoFeed(user_id=meu_id), timeout=t))
    log.ok(f"GetFeed de novo: {len(restantes)} perfis (Ana e Beatriz saíram do feed)")

    # 6) QuemMeCurtiu (server streaming) — do ponto de vista da Ana ---------
    curtidas = [p.nome for p in stub.QuemMeCurtiu(pb.PedidoQuemMeCurtiu(user_id="seed-1"), timeout=t)]
    log.ok(f"QuemMeCurtiu(seed-1): {curtidas}")

    # 7) Casos de erro: cada um deve voltar com o StatusCode certo ----------
    log.info("Testando erros (todos devem falhar com o código indicado):")
    esperar_erro("UpdateProfile de perfil inexistente",
                 lambda: stub.UpdateProfile(pb.PedidoAtualizarPerfil(user_id="nao-existe", nome="X"), timeout=t))
    esperar_erro("GetProfile de perfil inexistente",
                 lambda: stub.GetProfile(pb.PedidoPerfil(user_id="nao-existe"), timeout=t))
    esperar_erro("UpdateProfile sem nada para mudar",
                 lambda: stub.UpdateProfile(pb.PedidoAtualizarPerfil(user_id=meu_id), timeout=t))
    esperar_erro("Like em si mesmo",
                 lambda: stub.Like(pb.PedidoAvaliacao(de_user_id=meu_id, para_user_id=meu_id), timeout=t))
    esperar_erro("Like em perfil inexistente",
                 lambda: stub.Like(pb.PedidoAvaliacao(de_user_id=meu_id, para_user_id="nao-existe"), timeout=t))
    esperar_erro("CreateProfile com user_id repetido",
                 lambda: stub.CreateProfile(gerar_pedacos(meu_id, "Dup", "", foto, "jpg"), timeout=t))
    esperar_erro("CreateProfile sem foto",
                 lambda: stub.CreateProfile(gerar_pedacos(str(uuid.uuid4()), "Sem Foto", "", b"", "png"), timeout=t))
    esperar_erro("GetFeed sem user_id",
                 lambda: list(stub.GetFeed(pb.PedidoFeed(), timeout=t)))

    canal.close()
    log.ok("Todos os testes do Discovery concluídos")


if __name__ == "__main__":
    main()
