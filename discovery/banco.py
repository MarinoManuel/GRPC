"""
Acesso ao banco SQLite do Discovery (arquivo discovery/discovery.db).

Este serviço é o ÚNICO dono destas tabelas. Nenhum outro serviço abre
este arquivo; quem quiser perfis ou likes precisa pedir via gRPC.

Tabelas:
  perfis     -> um perfil por usuário. A foto NÃO fica no banco: guardamos
                só o caminho relativo do arquivo (ex.: "fotos/mulher-1.jpg").
  avaliacoes -> quem curtiu ('like') ou passou ('pass') quem.

Sobre conexões: o servidor gRPC atende várias chamadas em paralelo, cada
uma numa thread. Uma conexão SQLite não deve ser compartilhada entre
threads, então cada função abre a sua própria conexão, usa e fecha. É
um pouco menos eficiente, mas é o jeito mais simples e seguro.
"""

import sqlite3
from pathlib import Path

# Tudo relativo à pasta deste arquivo, nunca ao diretório de onde o
# comando foi executado. Assim o serviço funciona igual no PC e na VPS.
PASTA_SERVICO = Path(__file__).resolve().parent
CAMINHO_BANCO = PASTA_SERVICO / "discovery.db"

TAMANHO_LOTE_FEED = 5  # quantos perfis buscar do banco por vez no feed


def conectar():
    """Abre uma conexão nova com o banco (uma por chamada)."""
    conexao = sqlite3.connect(CAMINHO_BANCO, timeout=5)
    conexao.row_factory = sqlite3.Row  # permite linha["nome"] em vez de linha[1]
    return conexao


def criar_tabelas():
    """Cria as tabelas (se não existirem) e ativa o modo WAL."""
    with conectar() as conexao:
        # WAL (Write-Ahead Logging): leitores não ficam bloqueados enquanto
        # alguém escreve. Com várias chamadas simultâneas (feed sendo lido
        # enquanto alguém curte), isso evita erros de "database is locked".
        # A configuração fica gravada no próprio arquivo .db.
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.executescript("""
            CREATE TABLE IF NOT EXISTS perfis (
                user_id      TEXT PRIMARY KEY,
                nome         TEXT NOT NULL,
                bio          TEXT NOT NULL DEFAULT '',
                caminho_foto TEXT NOT NULL,
                criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- A chave primária (de, para) garante uma avaliação por par:
            -- se alguém passa e depois curte, a linha é substituída.
            CREATE TABLE IF NOT EXISTS avaliacoes (
                de_user_id   TEXT NOT NULL,
                para_user_id TEXT NOT NULL,
                tipo         TEXT NOT NULL CHECK (tipo IN ('like', 'pass')),
                criado_em    TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (de_user_id, para_user_id)
            );
        """)
    conexao.close()


def inserir_perfil(user_id, nome, bio, caminho_foto):
    """Cria um perfil. Retorna False se o user_id já existir."""
    with conectar() as conexao:
        try:
            conexao.execute(
                "INSERT INTO perfis (user_id, nome, bio, caminho_foto) VALUES (?, ?, ?, ?)",
                (user_id, nome, bio, caminho_foto),
            )
            sucesso = True
        except sqlite3.IntegrityError:
            sucesso = False
    conexao.close()
    return sucesso


def perfil_existe(user_id):
    """Diz se existe um perfil com esse user_id."""
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT 1 FROM perfis WHERE user_id = ?", (user_id,)
        ).fetchone()
    conexao.close()
    return linha is not None


def buscar_perfil(user_id):
    """Retorna a linha do perfil, ou None se não existir."""
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT user_id, nome, bio, caminho_foto FROM perfis WHERE user_id = ?", (user_id,)
        ).fetchone()
    conexao.close()
    return linha


def atualizar_perfil(user_id, nome=None, bio=None):
    """Atualiza nome e/ou bio (None = não mexer). Retorna False se o perfil não existir."""
    with conectar() as conexao:
        # COALESCE(?, nome) = "use o valor novo, ou mantenha o atual se vier NULL"
        cursor = conexao.execute(
            "UPDATE perfis SET nome = COALESCE(?, nome), bio = COALESCE(?, bio) WHERE user_id = ?",
            (nome, bio, user_id),
        )
        alterou = cursor.rowcount > 0
    conexao.close()
    return alterou


def buscar_lote_feed(user_id, depois_de_rowid, incluir_avaliados=False):
    """
    Busca o próximo lote de perfis para o feed de user_id.

    Exclui sempre o próprio usuário e, a menos que incluir_avaliados seja
    True, também quem ele já curtiu ou passou. Usa o rowid (número interno e
    crescente de cada linha no SQLite) para continuar de onde o lote
    anterior parou.
    """
    filtro_avaliados = "" if incluir_avaliados else \
        "AND user_id NOT IN (SELECT para_user_id FROM avaliacoes WHERE de_user_id = :eu)"
    with conectar() as conexao:
        linhas = conexao.execute(f"""
            SELECT rowid, user_id, nome, bio, caminho_foto
            FROM perfis
            WHERE rowid > :depois_de
              AND user_id != :eu
              {filtro_avaliados}
            ORDER BY rowid
            LIMIT :limite
        """, {"depois_de": depois_de_rowid, "eu": user_id, "limite": TAMANHO_LOTE_FEED}).fetchall()
    conexao.close()
    return linhas


def registrar_avaliacao(de_user_id, para_user_id, tipo):
    """Grava (ou substitui) um 'like' ou 'pass' de um usuário para outro."""
    with conectar() as conexao:
        conexao.execute(
            "INSERT OR REPLACE INTO avaliacoes (de_user_id, para_user_id, tipo) VALUES (?, ?, ?)",
            (de_user_id, para_user_id, tipo),
        )
    conexao.close()


def buscar_quem_curtiu(user_id):
    """Retorna os perfis de quem deu 'like' em user_id, do like mais recente ao mais antigo."""
    with conectar() as conexao:
        linhas = conexao.execute("""
            SELECT p.user_id, p.nome, p.bio, p.caminho_foto
            FROM avaliacoes a
            JOIN perfis p ON p.user_id = a.de_user_id
            WHERE a.para_user_id = ? AND a.tipo = 'like'
            ORDER BY a.criado_em DESC
        """, (user_id,)).fetchall()
    conexao.close()
    return linhas
