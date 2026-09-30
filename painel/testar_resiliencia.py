"""
Teste automático de resiliência: derruba serviços de verdade e confere o resto.

Rodar com NENHUM serviço no ar (o script sobe e derruba tudo sozinho):
    python -m painel.testar_resiliencia

Cenário 1 — o Messaging cai:
  - a aba Descobrir (feed, curtir, quem me curtiu) continua 100%;
  - a aba Chats responde 503, com mensagem clara;
  - editar o nome funciona e o nome vai para a fila;
  - quando o Messaging volta, a fila entrega o nome sozinha.
Cenário 2 — o Discovery cai:
  - a aba Chats (listar conversas e mandar mensagens) continua 100%;
  - a aba Descobrir responde 503;
  - um cadastro falha por inteiro e NADA é gravado (o login não funciona).

"Cair" aqui é matar o processo (kill), como um travamento ou queda de
energia, e não um desligamento educado.
Os logs de cada serviço ficam em painel/logs/.
"""

import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

from websockets.sync.client import connect

import config
from auth_gateway.testar_gateway import WS, cadastrar, chamar, receber_ate
from logs import Log

log = Log("RESILIENC")
RAIZ = Path(__file__).resolve().parent.parent
PASTA_LOGS = Path(__file__).resolve().parent / "logs"

resultados = {"ok": 0, "falhou": 0}
processos = {}


def verificar(descricao, condicao):
    """Registra um ✔ ou ✖ e conta o resultado."""
    if condicao:
        resultados["ok"] += 1
        log.ok(descricao)
    else:
        resultados["falhou"] += 1
        log.erro(f"FALHOU: {descricao}")


def subir(nome, modulo):
    """Inicia um serviço como processo separado, com o log indo para um arquivo."""
    arquivo_log = open(PASTA_LOGS / f"{nome}.log", "a", encoding="utf-8")
    processos[nome] = subprocess.Popen([sys.executable, "-m", modulo], cwd=RAIZ,
                                       stdout=arquivo_log, stderr=subprocess.STDOUT)
    log.info(f"{nome} iniciado (pid {processos[nome].pid})")


def derrubar(nome):
    """Mata o processo do serviço (simula uma queda de verdade)."""
    processos[nome].kill()
    processos[nome].wait()
    log.aviso(f"{nome} DERRUBADO (processo morto)")


def esperar(descricao, condicao, limite=30):
    """Espera até a condição ser verdadeira; devolve os segundos gastos ou None."""
    inicio = time.time()
    while time.time() - inicio < limite:
        try:
            if condicao():
                return time.time() - inicio
        except Exception:
            pass
        time.sleep(0.5)
    log.erro(f"Tempo esgotado esperando: {descricao}")
    return None


def status():
    """Atalho para o /api/status do Gateway."""
    return chamar("GET", "/api/status")[1]


def porta_ocupada(porta):
    """Diz se já tem algo escutando na porta (ex.: um serviço esquecido rodando)."""
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", porta)) == 0


def main():
    """Roda os dois cenários de queda e mostra o resumo."""
    portas = [config.AUTH_PORT, config.DISCOVERY_PORT, config.MESSAGING_PORT, config.GATEWAY_PORT]
    if any(porta_ocupada(p) for p in portas):
        log.erro(f"Alguma das portas {portas} já está em uso. Pare os serviços antes de rodar este teste.")
        return
    PASTA_LOGS.mkdir(exist_ok=True)

    try:
        # --- Preparação ------------------------------------------------------
        subir("discovery", "discovery.servidor")
        subir("messaging", "messaging.servidor")
        subir("gateway", "auth_gateway.gateway")
        def tudo_no_ar():
            s = status()
            return s["discovery"] == "SERVING" and s["messaging"] == "SERVING"
        verificar("Todos os serviços no ar", esperar("serviços no ar", tudo_no_ar) is not None)

        sufixo = uuid.uuid4().hex[:6]
        ana_id = cadastrar("Beatriz", f"bia{sufixo}@teste.com")[1]["user_id"]
        leo_id = cadastrar("Leo", f"leo{sufixo}@teste.com")[1]["user_id"]
        with connect(f"{WS}/ws/chat/{leo_id}?user_id={ana_id}") as ws:
            ws.send(json.dumps({"texto": "Oi Leo, primeira mensagem!"}))
            receber_ate(ws, 1)
        log.info("Beatriz e Leo cadastrados e já com uma conversa iniciada")

        # --- Cenário 1: Messaging cai ----------------------------------------
        print()
        log.aviso("===== CENÁRIO 1: o Messaging cai =====")
        derrubar("messaging")
        esperar("Gateway perceber a queda", lambda: status()["messaging"].startswith("FORA"))

        verificar("Feed continua funcionando", chamar("GET", "/api/feed", user_id=ana_id)[0] == 200)
        verificar("Curtir continua funcionando",
                  chamar("POST", f"/api/perfis/{leo_id}/curtir", user_id=ana_id)[0] == 200)
        verificar("Quem me curtiu continua funcionando",
                  chamar("GET", "/api/quem-me-curtiu", user_id=leo_id)[0] == 200)
        codigo, corpo = chamar("GET", "/api/conversas", user_id=leo_id)
        verificar(f"Lista de conversas responde 503 com mensagem clara ({corpo.get('detail')!r})",
                  codigo == 503)

        codigo, corpo = chamar("PATCH", "/api/meu-perfil", {"nome": "Bia"}, user_id=ana_id)
        verificar(f"Editar nome funciona mesmo assim ({corpo})",
                  codigo == 200 and corpo.get("nome_nos_chats") == "pendente")
        codigo, _ = cadastrar("Nina", f"nina{sufixo}@teste.com")
        verificar("Cadastro funciona com o Messaging fora (nome da Nina vai para a fila)", codigo == 201)
        pendentes = status()["nomes_pendentes"]
        verificar(f"Fila tem {pendentes} nome(s) pendente(s)", pendentes >= 2)

        log.info("Esperando alguns ciclos de retry com backoff (veja o log do gateway)...")
        time.sleep(7)
        subir("messaging", "messaging.servidor")
        segundos = esperar("fila esvaziar", lambda: status()["nomes_pendentes"] == 0, limite=90)
        verificar(f"Messaging voltou e a fila se esvaziou sozinha em {segundos or 0:.1f}s",
                  segundos is not None)
        codigo, conversas = chamar("GET", "/api/conversas", user_id=leo_id)
        nome_visto = conversas[0]["outro_nome"] if codigo == 200 and conversas else None
        verificar(f"Leo agora vê a conversa com '{nome_visto}' (nome sincronizado)", nome_visto == "Bia")

        # --- Cenário 2: Discovery cai ----------------------------------------
        print()
        log.aviso("===== CENÁRIO 2: o Discovery cai =====")
        derrubar("discovery")
        esperar("Gateway perceber a queda", lambda: status()["discovery"].startswith("FORA"))

        verificar("Lista de conversas continua funcionando",
                  chamar("GET", "/api/conversas", user_id=leo_id)[0] == 200)
        with connect(f"{WS}/ws/chat/{leo_id}?user_id={ana_id}") as ws_bia, \
             connect(f"{WS}/ws/chat/{ana_id}?user_id={leo_id}") as ws_leo:
            receber_ate(ws_bia, 1, limite=1)  # descarta o histórico
            receber_ate(ws_leo, 1, limite=1)
            ws_leo.send(json.dumps({"texto": "Oi Bia! O Discovery caiu, mas o chat não."}))
            recebidas = [m for m in receber_ate(ws_bia, 3, limite=3) if "Discovery caiu" in m.get("texto", "")]
            verificar("Mandar e receber mensagens continua funcionando", len(recebidas) == 1)

        verificar("Feed responde 503", chamar("GET", "/api/feed", user_id=ana_id)[0] == 503)
        email_zeca = f"zeca{sufixo}@teste.com"
        codigo, corpo = cadastrar("Zeca", email_zeca)
        verificar(f"Cadastro falha por inteiro ({codigo}: {corpo.get('detail')!r})", codigo == 503)
        codigo, _ = chamar("POST", "/api/login", {"email": email_zeca, "senha": "abc"})
        verificar("Login do Zeca falha: a credencial NÃO foi gravada (sem cadastro pela metade)",
                  codigo == 401)
        codigo, _ = chamar("PATCH", "/api/meu-perfil", {"nome": "Beatriz"}, user_id=ana_id)
        verificar("Editar nome responde 503 e nada vai para a fila",
                  codigo == 503 and status()["nomes_pendentes"] == 0)

        subir("discovery", "discovery.servidor")
        segundos = esperar("feed voltar", lambda: chamar("GET", "/api/feed", user_id=ana_id)[0] == 200)
        verificar(f"Discovery voltou e o feed funciona de novo ({segundos or 0:.1f}s)", segundos is not None)

    finally:
        for processo in processos.values():
            processo.kill()
        print()
        total = resultados["ok"] + resultados["falhou"]
        resumo = f"{resultados['ok']}/{total} verificações passaram. Logs em {PASTA_LOGS}"
        (log.ok if resultados["falhou"] == 0 else log.erro)(resumo)


if __name__ == "__main__":
    main()
