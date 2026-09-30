"""
Sincronização de nomes com o Messaging: fila de retry com backoff exponencial.

O PROBLEMA
  O Messaging guarda a sua própria cópia do nome de cada usuário, para não
  depender do Discovery ao mostrar os chats. Quando alguém muda o nome, essa
  cópia precisa ser atualizada. Mas e se o Messaging estiver fora do ar
  nesse momento? Se só registrássemos o erro, a cópia ficaria errada PARA
  SEMPRE.

POR QUE O gRPC NÃO RESOLVE SOZINHO
  - A reconexão automática do gRPC só restabelece a CONEXÃO de rede; ela
    não lembra de reenviar uma chamada que já falhou.
  - A política de retry embutida do gRPC tenta poucas vezes, em poucos
    segundos. Se o serviço ficar 10 minutos fora, ela já desistiu.

A SOLUÇÃO (versão simplificada do "Outbox Pattern")
  1. Tenta entregar na hora (Messaging.AtualizarNome).
  2. Se falhar, grava o nome numa tabela local do Gateway
     (fila_nomes_pendentes). Como está em disco, sobrevive até a um
     reinício do Gateway.
  3. Uma tarefa em segundo plano varre essa tabela a cada 1s e tenta de
     novo cada pendência cujo horário chegou. A cada falha, a espera DOBRA:
     2s, 4s, 8s, 16s, 32s, 60s, 60s, 60s... (teto de 60s). Assim não
     martelamos um serviço que está fora do ar, mas também nunca desistimos.
  4. Quando o Messaging confirma, a linha é apagada.
"""

import asyncio
import time

import grpc

import config
from auth_gateway import banco, clientes
from gerado import messaging_pb2
from logs import Log

log = Log("FILA")

ESPERA_INICIAL_SEGUNDOS = 2
ESPERA_MAXIMA_SEGUNDOS = 60
INTERVALO_VARREDURA_SEGUNDOS = 1

# Garante que só UMA entrega de nome acontece por vez. Sem isso, a tarefa de
# fundo poderia estar enviando um nome ANTIGO enquanto a pessoa salva um nome
# NOVO; se a resposta antiga chegasse por último, o Messaging ficaria com o
# nome errado. Com a trava, as entregas acontecem em fila, na ordem certa.
_trava_entrega = asyncio.Lock()


def calcular_espera(tentativas):
    """Backoff exponencial: 2s, 4s, 8s... dobrando a cada falha, até 60s."""
    return min(ESPERA_INICIAL_SEGUNDOS * 2 ** (tentativas - 1), ESPERA_MAXIMA_SEGUNDOS)


async def _enviar_ao_messaging(user_id, novo_nome):
    """Chamada gRPC propriamente dita (com deadline). Lança grpc.RpcError se falhar."""
    await clientes.messaging.AtualizarNome(
        messaging_pb2.PedidoAtualizarNome(user_id=user_id, novo_nome=novo_nome),
        timeout=config.TIMEOUT_SEGUNDOS)


async def sincronizar_nome(user_id, novo_nome):
    """
    Tenta atualizar o nome no Messaging agora; se falhar, põe na fila.

    Retorna True se entregou na hora e False se ficou pendente. Nunca lança
    erro: para quem chamou (ex.: a rota de editar perfil), a mudança de nome
    já deu certo no Discovery; a cópia do Messaging chega "eventualmente".
    """
    async with _trava_entrega:
        try:
            await _enviar_ao_messaging(user_id, novo_nome)
            # Se havia um nome mais antigo na fila, ele ficou obsoleto.
            banco.remover_pendencia(user_id)
            log.ok(f"Nome de {user_id} sincronizado com o Messaging: '{novo_nome}'")
            return True
        except grpc.RpcError as erro:
            espera = calcular_espera(1)
            banco.enfileirar_nome(user_id, novo_nome, tentativas=1,
                                  proxima_tentativa_em=time.time() + espera)
            log.aviso(f"Messaging não respondeu ({erro.code().name}); nome '{novo_nome}' "
                      f"de {user_id} guardado na fila, nova tentativa em {espera}s")
            return False


async def _tentar_pendencia(user_id):
    """Uma tentativa de entrega de uma pendência da fila."""
    async with _trava_entrega:
        # Relê DENTRO da trava: enquanto esperávamos, a pendência pode ter
        # sido entregue ou substituída por um nome mais novo.
        pendencia = banco.buscar_pendencia(user_id)
        if pendencia is None:
            return
        tentativa = pendencia["tentativas"] + 1
        try:
            await _enviar_ao_messaging(user_id, pendencia["novo_nome"])
            banco.remover_pendencia(user_id)
            log.ok(f"Fila: nome '{pendencia['novo_nome']}' de {user_id} entregue "
                   f"na tentativa {tentativa}")
        except grpc.RpcError as erro:
            espera = calcular_espera(tentativa)
            banco.reagendar_pendencia(user_id, tentativa, time.time() + espera)
            log.aviso(f"Fila: tentativa {tentativa} para {user_id} falhou "
                      f"({erro.code().name}); próxima em {espera}s")


async def varrer_fila_para_sempre():
    """Tarefa de fundo do Gateway: reenvia as pendências vencidas, para sempre.

    É uma tarefa assíncrona (asyncio) em vez de uma thread: roda "ao lado"
    das requisições no mesmo processo, que é o equivalente assíncrono de
    uma thread em segundo plano, e usa os mesmos canais gRPC do Gateway.
    """
    pendentes = banco.contar_pendencias()
    if pendentes:
        log.info(f"{pendentes} nome(s) pendente(s) encontrados na fila ao iniciar")
    while True:
        await asyncio.sleep(INTERVALO_VARREDURA_SEGUNDOS)
        try:
            for pendencia in banco.buscar_pendencias_vencidas(time.time()):
                await _tentar_pendencia(pendencia["user_id"])
        except Exception as erro:  # a varredura nunca pode morrer
            log.erro(f"Erro inesperado na varredura da fila: {erro!r}")
