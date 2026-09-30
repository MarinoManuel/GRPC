"""
Teste de ponta a ponta do Gateway, como um frontend faria (REST + WebSocket).

Rodar com Discovery, Messaging e Gateway no ar:
    python -m auth_gateway.testar_gateway

Usa só a biblioteca padrão (urllib) para o REST e o cliente "websockets"
(que já vem com o uvicorn[standard]) para o chat.
"""

import base64
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from websockets.sync.client import connect

import config
from logs import Log

log = Log("TESTE")
# 127.0.0.1 em vez de "localhost": no Windows, "localhost" tenta primeiro
# IPv6 (::1), e como o Gateway escuta só em IPv4 (0.0.0.0), cada requisição
# perderia ~2s até cair para IPv4.
BASE = f"http://127.0.0.1:{config.GATEWAY_PORT}"
WS = f"ws://127.0.0.1:{config.GATEWAY_PORT}"
FOTO = Path(__file__).resolve().parent.parent / "discovery" / "fotos" / "mulher-4.jpg"


def chamar(metodo, caminho, corpo=None, user_id=None):
    """Faz uma requisição HTTP e devolve (status, json). Não lança erro em 4xx/5xx."""
    dados = json.dumps(corpo).encode() if corpo is not None else None
    pedido = urllib.request.Request(BASE + caminho, data=dados, method=metodo)
    pedido.add_header("Content-Type", "application/json")
    if user_id:
        pedido.add_header("X-User-Id", user_id)
    try:
        with urllib.request.urlopen(pedido, timeout=40) as resposta:
            corpo = resposta.read()
            # O feed vem em NDJSON (um JSON por linha, enviado aos poucos):
            # aqui juntamos as linhas numa lista para os testes.
            if "ndjson" in resposta.headers.get("Content-Type", ""):
                return resposta.status, [json.loads(l) for l in corpo.splitlines() if l.strip()]
            return resposta.status, json.loads(corpo)
    except urllib.error.HTTPError as erro:
        return erro.code, json.loads(erro.read())


def conferir(descricao, obtido, esperado):
    """Mostra ✔ se o status HTTP é o esperado, ✖ se não."""
    if obtido == esperado:
        log.ok(f"{descricao} -> {obtido}")
    else:
        log.erro(f"{descricao} -> {obtido} (esperado {esperado})")
    return obtido == esperado


def cadastrar(nome, email):
    """Cadastra um usuário de teste com a foto mulher-4.jpg."""
    foto = base64.b64encode(FOTO.read_bytes()).decode()
    return chamar("POST", "/api/cadastro", {"email": email, "senha": "abc", "nome": nome,
                                            "bio": f"Bio de {nome}", "foto_base64": foto,
                                            "extensao_foto": "png"})


def receber_ate(ws, quantidade, limite=5):
    """Lê mensagens do WebSocket até juntar 'quantidade' ou estourar o tempo."""
    recebidas = []
    fim = time.time() + limite
    while len(recebidas) < quantidade and time.time() < fim:
        try:
            recebidas.append(json.loads(ws.recv(timeout=fim - time.time())))
        except TimeoutError:
            break
    return recebidas


def main():
    """Percorre o fluxo completo de uso: cadastro, login, feed, like, perfil, chat."""
    sufixo = uuid.uuid4().hex[:6]
    email_c, email_d = f"carol{sufixo}@teste.com", f"davi{sufixo}@teste.com"

    status, corpo = chamar("GET", "/api/status")
    log.info(f"Status dos serviços: {corpo}")

    # --- Cadastro e login ----------------------------------------------------
    status, corpo = cadastrar("Carol", email_c)
    conferir("Cadastro Carol", status, 201)
    carol = corpo["user_id"]
    status, corpo = cadastrar("Davi", email_d)
    conferir("Cadastro Davi", status, 201)
    davi = corpo["user_id"]
    conferir("Cadastro com e-mail repetido", cadastrar("Carol2", email_c)[0], 409)

    status, corpo = chamar("POST", "/api/login", {"email": email_c, "senha": "abc"})
    conferir("Login da Carol", status, 200)
    conferir("Login devolve o mesmo user_id", corpo["user_id"] == carol, True)
    conferir("Login com senha errada", chamar("POST", "/api/login", {"email": email_c, "senha": "x"})[0], 401)
    conferir("Rota protegida sem sessão válida", chamar("GET", "/api/feed", user_id="inventado")[0], 401)

    # --- Aba Descobrir -------------------------------------------------------
    status, perfis = chamar("GET", "/api/feed", user_id=carol)
    conferir(f"Feed da Carol ({len(perfis)} perfis)", status, 200)
    nomes = [p["nome"] for p in perfis]
    log.info(f"  Feed: {nomes[:8]}{' ...' if len(nomes) > 8 else ''}")
    conferir("Feed traz o Davi", "Davi" in nomes, True)
    conferir("Feed não traz a própria Carol", carol in [p["user_id"] for p in perfis], False)
    conferir("Foto vem como data URL", perfis[0]["foto"].startswith("data:image/png;base64,"), True)

    conferir("Carol curte Davi", chamar("POST", f"/api/perfis/{davi}/curtir", user_id=carol)[0], 200)
    conferir("Curtir perfil inexistente", chamar("POST", "/api/perfis/nao-existe/curtir", user_id=carol)[0], 404)
    status, curtidas = chamar("GET", "/api/quem-me-curtiu", user_id=davi)
    conferir("Quem curtiu o Davi inclui a Carol", [p["nome"] for p in curtidas] == ["Carol"], True)

    # --- Editar perfil (e sincronizar o nome com o Messaging) ---------------
    status, corpo = chamar("PATCH", "/api/meu-perfil", {"nome": "Carolina"}, user_id=carol)
    conferir(f"Carol vira Carolina ({corpo})", status, 200)
    conferir("Nome vazio é recusado", chamar("PATCH", "/api/meu-perfil", {"nome": " "}, user_id=carol)[0], 400)

    # --- Chat via WebSocket (sem ter curtido: chat é independente do like) ---
    with connect(f"{WS}/ws/chat/{davi}?user_id={carol}") as ws_carol, \
         connect(f"{WS}/ws/chat/{carol}?user_id={davi}") as ws_davi:
        time.sleep(0.3)
        ws_carol.send(json.dumps({"texto": "Oi Davi! Vi seu perfil."}))
        recebida = receber_ate(ws_davi, 1)
        conferir(f"Davi recebe em tempo real: {recebida[0]['de_nome']}: {recebida[0]['texto']!r}"
                 if recebida else "Davi recebe em tempo real", len(recebida), 1)
        ws_davi.send(json.dumps({"texto": "Oi Carolina!"}))
        recebidas = receber_ate(ws_carol, 2)  # a própria (confirmação) + a do Davi
        conferir("Carolina recebe a resposta", [m["texto"] for m in recebidas][-1:], ["Oi Carolina!"])

    status, lista = chamar("GET", "/api/conversas", user_id=davi)
    conferir("Conversas do Davi", status, 200)
    if lista:
        log.info(f"  Conversa com {lista[0]['outro_nome']!r}: última {lista[0]['ultima_mensagem']!r}")
        conferir("Messaging já mostra o nome novo 'Carolina'", lista[0]["outro_nome"], "Carolina")

    log.ok("Teste do Gateway concluído")


if __name__ == "__main__":
    main()
