"""
Cria os 5 perfis de seed no banco do Discovery.

Rodar uma vez (as fotos mulher-1.jpg ... mulher-5.jpg ficam em discovery/fotos/):
    python -m discovery.seed

Os user_id são fixos ("seed-1" ... "seed-5") e a inserção ignora perfis
que já existem, então rodar de novo não duplica nada.
"""

from discovery import banco
from logs import Log

log = Log("SEED")

PERFIS_SEED = [
    ("seed-1", "Ana", "Café coado, fone no ouvido e caminhadas sem destino pela cidade."),
    ("seed-2", "Beatriz", "Pôr do sol na praia é meu programa favorito. Topa um açaí depois?"),
    ("seed-3", "Carla", "Leitora compulsiva, fã de anime e mãe de planta. Me indica um livro?"),
    ("seed-4", "Daniela", "Sorriso fácil, samba no fim de semana e sempre a última a ir embora."),
    ("seed-5", "Elisa", "Treino de manhã, brunch depois. Procuro alguém pra dividir a playlist."),
]


def rodar_seed():
    """Garante que as tabelas existem e insere os perfis de seed."""
    banco.criar_tabelas()
    for i, (user_id, nome, bio) in enumerate(PERFIS_SEED, start=1):
        # Caminho RELATIVO à pasta do serviço: se a pasta inteira for
        # copiada para outra máquina, o caminho continua válido.
        caminho_foto = f"fotos/mulher-{i}.jpg"
        if not (banco.PASTA_SERVICO / caminho_foto).exists():
            log.erro(f"Foto discovery/{caminho_foto} não encontrada")
            return
        if banco.inserir_perfil(user_id, nome, bio, caminho_foto):
            log.ok(f"Perfil criado: {nome} ({user_id})")
        else:
            log.aviso(f"Perfil {nome} ({user_id}) já existia, ignorado")


if __name__ == "__main__":
    rodar_seed()
