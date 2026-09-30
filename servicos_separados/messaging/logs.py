"""
Logs coloridos e padronizados para o terminal.

Todos os serviços usam este mesmo formato, para que durante a demonstração
dê para bater o olho e saber QUEM disse O QUÊ e QUANDO:

    14:02:31 [DISCOVERY] ✔ Perfil criado: Ana (id=3f2a...)
    14:02:35 [GATEWAY  ] ✖ Messaging fora do ar: UNAVAILABLE

Usa códigos ANSI (sem biblioteca externa). O terminal do VS Code, o Windows
Terminal e os terminais Linux dos servidores entendem esses códigos.
"""

import os
import sys
from datetime import datetime

# No Windows, esta chamada vazia "liga" o suporte a cores ANSI em consoles
# antigos (cmd.exe clássico). Em terminais modernos não faz diferença.
if os.name == "nt":
    os.system("")

# Garante que ✔ ✖ ⚠ não quebrem em consoles Windows com codificação antiga.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# Só usa cores quando a saída é um terminal de verdade. Rodando como
# serviço systemd, a saída vai para o journal, e lá os códigos de cor
# fariam o "journalctl" mostrar as linhas como "[blob data]".
USAR_CORES = sys.stdout.isatty()


def _cor(codigo):
    return codigo if USAR_CORES else ""


RESET = _cor("\033[0m")
CINZA = _cor("\033[90m")
VERDE = _cor("\033[92m")
AMARELO = _cor("\033[93m")
VERMELHO = _cor("\033[91m")
AZUL = _cor("\033[94m")
NEGRITO = _cor("\033[1m")


class Log:
    """Logger simples: cada serviço cria um com seu nome, ex.: Log("DISCOVERY")."""

    def __init__(self, nome_servico):
        # Largura fixa para as colunas ficarem alinhadas entre serviços.
        self.etiqueta = f"[{nome_servico:<9}]"

    def _escrever(self, cor, simbolo, mensagem):
        hora = datetime.now().strftime("%H:%M:%S")
        # flush=True: com o serviço rodando em segundo plano (systemd),
        # sem isso as linhas podem demorar a aparecer no log.
        print(f"{CINZA}{hora}{RESET} {NEGRITO}{self.etiqueta}{RESET} "
              f"{cor}{simbolo} {mensagem}{RESET}", flush=True)

    def info(self, mensagem):
        """Evento normal (chegou uma chamada, enviou um perfil...)."""
        self._escrever(AZUL, "•", mensagem)

    def ok(self, mensagem):
        """Algo concluído com sucesso."""
        self._escrever(VERDE, "✔", mensagem)

    def aviso(self, mensagem):
        """Problema esperado/tratado (dado inválido, retry agendado...)."""
        self._escrever(AMARELO, "⚠", mensagem)

    def erro(self, mensagem):
        """Falha real (outro serviço fora do ar, exceção...)."""
        self._escrever(VERMELHO, "✖", mensagem)


if __name__ == "__main__":
    # "python logs.py" mostra como cada nível aparece no seu terminal.
    log = Log("TESTE")
    log.info("mensagem informativa")
    log.ok("operação concluída")
    log.aviso("algo esperado deu errado e foi tratado")
    log.erro("serviço fora do ar")
