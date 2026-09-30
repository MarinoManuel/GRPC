"""
Acesso ao banco SQLite do Messaging (arquivo messaging/messaging.db).

Tabelas:
  mensagens -> todas as mensagens trocadas. É a ÚNICA fonte de verdade
               sobre conversas: não existe tabela de "conversas" nem de
               "permissões". Uma conversa existe se há ao menos uma
               mensagem entre duas pessoas.
  nomes     -> cópia local (cache) do nome de cada usuário, para exibir
               nas conversas sem nunca perguntar ao Discovery. Quem mantém
               esta tabela em dia é o Gateway, via AtualizarNome.

Assim como no Discovery, cada função abre e fecha a sua própria conexão,
porque o servidor gRPC atende chamadas em várias threads ao mesmo tempo.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PASTA_SERVICO = Path(__file__).resolve().parent
CAMINHO_BANCO = PASTA_SERVICO / "messaging.db"

NOME_PADRAO = "Usuário"   # usado enquanto o nome real não chega via AtualizarNome
LIMITE_HISTORICO = 50     # quantas mensagens antigas enviar ao abrir um chat


def conectar():
    """Abre uma conexão nova com o banco (uma por chamada)."""
    conexao = sqlite3.connect(CAMINHO_BANCO, timeout=5)
    conexao.row_factory = sqlite3.Row
    return conexao


def criar_tabelas():
    """Cria as tabelas (se não existirem) e ativa o modo WAL."""
    with conectar() as conexao:
        # WAL: leituras (histórico, lista de conversas) não bloqueiam a
        # gravação de mensagens novas, e vice-versa.
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.executescript("""
            CREATE TABLE IF NOT EXISTS mensagens (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                de_user_id   TEXT NOT NULL,
                para_user_id TEXT NOT NULL,
                texto        TEXT NOT NULL,
                enviada_em   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mensagens_de   ON mensagens (de_user_id);
            CREATE INDEX IF NOT EXISTS idx_mensagens_para ON mensagens (para_user_id);

            CREATE TABLE IF NOT EXISTS nomes (
                user_id       TEXT PRIMARY KEY,
                nome          TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );
        """)
    conexao.close()


def agora_utc():
    """Data/hora atual em UTC no formato ISO 8601.

    UTC porque os servidores podem estar em fusos diferentes; quem exibe
    (o frontend) converte para o horário local de cada pessoa.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def salvar_mensagem(de_user_id, para_user_id, texto):
    """Grava uma mensagem e devolve a linha completa (com id e horário)."""
    enviada_em = agora_utc()
    with conectar() as conexao:
        cursor = conexao.execute(
            "INSERT INTO mensagens (de_user_id, para_user_id, texto, enviada_em) VALUES (?, ?, ?, ?)",
            (de_user_id, para_user_id, texto, enviada_em),
        )
        novo_id = cursor.lastrowid
    conexao.close()
    return {"id": novo_id, "de_user_id": de_user_id, "para_user_id": para_user_id,
            "texto": texto, "enviada_em": enviada_em}


def buscar_historico(user_a, user_b):
    """Últimas mensagens trocadas entre dois usuários, da mais antiga para a mais nova."""
    with conectar() as conexao:
        # A subconsulta pega as N mais RECENTES (ORDER BY id DESC LIMIT N);
        # a consulta de fora as coloca de volta em ordem cronológica.
        linhas = conexao.execute("""
            SELECT * FROM (
                SELECT id, de_user_id, para_user_id, texto, enviada_em
                FROM mensagens
                WHERE (de_user_id = ? AND para_user_id = ?)
                   OR (de_user_id = ? AND para_user_id = ?)
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id
        """, (user_a, user_b, user_b, user_a, LIMITE_HISTORICO)).fetchall()
    conexao.close()
    return linhas


def listar_conversas(user_id):
    """
    Deriva a lista de conversas direto da tabela de mensagens.

    Passo a passo da consulta:
      1. Pega toda mensagem em que user_id é remetente OU destinatário.
      2. Para cada uma, descobre quem é "o outro" (CASE WHEN).
      3. Agrupa por "o outro" e guarda o id da mensagem mais recente (MAX).
      4. Junta com a própria tabela para pegar o texto dessa mensagem, e
         com o cache de nomes para exibir quem é quem.
      5. Ordena da conversa mais recente para a mais antiga.
    """
    with conectar() as conexao:
        linhas = conexao.execute("""
            SELECT c.outro_user_id,
                   COALESCE(n.nome, ?) AS outro_nome,
                   m.texto             AS ultima_mensagem,
                   m.enviada_em        AS ultima_em
            FROM (
                SELECT CASE WHEN de_user_id = ? THEN para_user_id ELSE de_user_id END AS outro_user_id,
                       MAX(id) AS ultimo_id
                FROM mensagens
                WHERE de_user_id = ? OR para_user_id = ?
                GROUP BY outro_user_id
            ) c
            JOIN mensagens m ON m.id = c.ultimo_id
            LEFT JOIN nomes n ON n.user_id = c.outro_user_id
            ORDER BY c.ultimo_id DESC
        """, (NOME_PADRAO, user_id, user_id, user_id)).fetchall()
    conexao.close()
    return linhas


def buscar_nome(user_id):
    """Nome em cache do usuário, ou o nome padrão se ainda não sincronizado."""
    with conectar() as conexao:
        linha = conexao.execute("SELECT nome FROM nomes WHERE user_id = ?", (user_id,)).fetchone()
    conexao.close()
    return linha["nome"] if linha else NOME_PADRAO


def salvar_nome(user_id, nome):
    """Grava ou substitui o nome em cache de um usuário."""
    with conectar() as conexao:
        conexao.execute(
            "INSERT OR REPLACE INTO nomes (user_id, nome, atualizado_em) VALUES (?, ?, ?)",
            (user_id, nome, agora_utc()),
        )
    conexao.close()
