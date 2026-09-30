"""
Cria credenciais de login para os 5 perfis de seed do Discovery.

Rodar uma vez:  python -m auth_gateway.seed

Os perfis seed-1..seed-5 existem só no Discovery (criados por
discovery/seed.py). Com isto, dá para entrar como a Ana, por exemplo, e
responder às mensagens durante a demonstração:
    ana@seed.com / 123     beatriz@seed.com / 123     ...

Os nomes também são colocados na fila de sincronização, para o Messaging
passar a exibir "Ana" em vez de "Usuário". A entrega acontece sozinha
assim que o Gateway estiver rodando e o Messaging estiver no ar: é a
mesma fila usada quando alguém edita o nome.

(A lista de nomes repete a de discovery/seed.py de propósito: o Gateway
não importa código de outro serviço, assim como não lê o banco dele.)
"""

import time

from auth_gateway import banco
from logs import Log

log = Log("SEED")

PERFIS_SEED = [("seed-1", "Ana"), ("seed-2", "Beatriz"), ("seed-3", "Carla"),
               ("seed-4", "Daniela"), ("seed-5", "Elisa")]
SENHA_SEED = "123"


def rodar_seed():
    """Insere as credenciais dos perfis de seed e agenda a sincronização dos nomes."""
    banco.criar_tabelas()
    for user_id, nome in PERFIS_SEED:
        email = f"{nome.lower()}@seed.com"
        if banco.inserir_credencial(user_id, email, SENHA_SEED):
            # tentativas=0 e horário "agora": a tarefa de fundo do Gateway
            # entrega na primeira varredura.
            banco.enfileirar_nome(user_id, nome, tentativas=0, proxima_tentativa_em=time.time())
            log.ok(f"Credencial criada: {email} / {SENHA_SEED} ({user_id})")
        else:
            log.aviso(f"Credencial de {email} já existia, ignorada")


if __name__ == "__main__":
    rodar_seed()
