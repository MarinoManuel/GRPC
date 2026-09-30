"""
Acesso ao banco SQLite do Auth + Gateway (arquivo auth_gateway/auth.db).

Tabelas:
  credenciais          -> {user_id, email, senha}. Nada de perfil aqui:
                          nome/bio/foto são do Discovery.
  fila_nomes_pendentes -> nomes que o Gateway ainda precisa entregar ao
                          Messaging (a "caixa de saída" do Outbox Pattern).
                          Uma linha por usuário: se o nome mudar de novo
                          antes da entrega, a linha é SUBSTITUÍDA, então
                          nunca se acumulam nomes antigos.

As funções aqui são síncronas e rápidas (SQLite local). O Gateway é
assíncrono (FastAPI), mas uma consulta de microssegundos num arquivo local
não justifica a complexidade de um driver assíncrono.
"""

import sqlite3
from pathlib import Path

PASTA_SERVICO = Path(__file__).resolve().parent
CAMINHO_BANCO = PASTA_SERVICO / "auth.db"


def conectar():
    """Abre uma conexão nova com o banco (uma por chamada)."""
    conexao = sqlite3.connect(CAMINHO_BANCO, timeout=5)
    conexao.row_factory = sqlite3.Row
    return conexao


def criar_tabelas():
    """Cria as tabelas (se não existirem) e ativa o modo WAL."""
    with conectar() as conexao:
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.executescript("""
            CREATE TABLE IF NOT EXISTS credenciais (
                user_id   TEXT PRIMARY KEY,
                email     TEXT NOT NULL UNIQUE,
                senha     TEXT NOT NULL,  -- texto puro: fora de escopo (didático)
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS fila_nomes_pendentes (
                user_id              TEXT PRIMARY KEY,
                novo_nome            TEXT NOT NULL,
                proxima_tentativa_em REAL NOT NULL,   -- horário Unix (time.time())
                tentativas           INTEGER NOT NULL -- quantas já falharam
            );
        """)
    conexao.close()


# ----- Credenciais -----------------------------------------------------------

def email_existe(email):
    """Diz se o e-mail já está cadastrado."""
    with conectar() as conexao:
        linha = conexao.execute("SELECT 1 FROM credenciais WHERE email = ?", (email,)).fetchone()
    conexao.close()
    return linha is not None


def inserir_credencial(user_id, email, senha):
    """Grava uma credencial. Retorna False se o e-mail ou o id já existirem."""
    with conectar() as conexao:
        try:
            conexao.execute("INSERT INTO credenciais (user_id, email, senha) VALUES (?, ?, ?)",
                            (user_id, email, senha))
            sucesso = True
        except sqlite3.IntegrityError:
            sucesso = False
    conexao.close()
    return sucesso


def buscar_user_id(email, senha):
    """Retorna o user_id se e-mail e senha conferem; senão None."""
    with conectar() as conexao:
        linha = conexao.execute("SELECT user_id FROM credenciais WHERE email = ? AND senha = ?",
                                (email, senha)).fetchone()
    conexao.close()
    return linha["user_id"] if linha else None


def usuario_existe(user_id):
    """Diz se existe credencial com esse user_id (usado para validar a "sessão")."""
    with conectar() as conexao:
        linha = conexao.execute("SELECT 1 FROM credenciais WHERE user_id = ?", (user_id,)).fetchone()
    conexao.close()
    return linha is not None


# ----- Fila de nomes pendentes (Outbox) --------------------------------------

def enfileirar_nome(user_id, novo_nome, tentativas, proxima_tentativa_em):
    """Guarda (ou substitui) o nome pendente de um usuário."""
    with conectar() as conexao:
        # INSERT OR REPLACE chaveado por user_id: se já havia um nome
        # pendente mais antigo, ele é descartado. Só o mais novo importa.
        conexao.execute("""
            INSERT OR REPLACE INTO fila_nomes_pendentes
                (user_id, novo_nome, proxima_tentativa_em, tentativas)
            VALUES (?, ?, ?, ?)
        """, (user_id, novo_nome, proxima_tentativa_em, tentativas))
    conexao.close()


def buscar_pendencias_vencidas(agora):
    """Pendências cujo horário de nova tentativa já chegou."""
    with conectar() as conexao:
        linhas = conexao.execute(
            "SELECT * FROM fila_nomes_pendentes WHERE proxima_tentativa_em <= ? ORDER BY proxima_tentativa_em",
            (agora,)).fetchall()
    conexao.close()
    return linhas


def buscar_pendencia(user_id):
    """A pendência atual de um usuário (ou None)."""
    with conectar() as conexao:
        linha = conexao.execute("SELECT * FROM fila_nomes_pendentes WHERE user_id = ?", (user_id,)).fetchone()
    conexao.close()
    return linha


def reagendar_pendencia(user_id, tentativas, proxima_tentativa_em):
    """Registra mais uma falha e o horário da próxima tentativa."""
    with conectar() as conexao:
        conexao.execute(
            "UPDATE fila_nomes_pendentes SET tentativas = ?, proxima_tentativa_em = ? WHERE user_id = ?",
            (tentativas, proxima_tentativa_em, user_id))
    conexao.close()


def remover_pendencia(user_id):
    """Tira o usuário da fila (nome entregue ao Messaging)."""
    with conectar() as conexao:
        conexao.execute("DELETE FROM fila_nomes_pendentes WHERE user_id = ?", (user_id,))
    conexao.close()


def contar_pendencias():
    """Quantos nomes aguardam entrega (mostrado no /api/status e no painel)."""
    with conectar() as conexao:
        total = conexao.execute("SELECT COUNT(*) FROM fila_nomes_pendentes").fetchone()[0]
    conexao.close()
    return total
