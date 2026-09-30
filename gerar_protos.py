"""
Gera o código Python a partir dos arquivos .proto.

Para cada arquivo protos/X.proto, gera em gerado/:
    X_pb2.py        -> as classes das mensagens (PedidoFeed, Perfil...)
    X_pb2_grpc.py   -> o "Servicer" (base do servidor) e o "Stub" (cliente)
    X_pb2.pyi       -> dicas de tipo, só para o autocompletar do editor

"""

import sys
from pathlib import Path

from grpc_tools import protoc

RAIZ = Path(__file__).resolve().parent
PROTOS = ["auth.proto", "discovery.proto", "messaging.proto"]


def gerar():
    """Chama o compilador protoc (embutido no grpcio-tools) para cada .proto."""
    for nome in PROTOS:
        # O truque "-Igerado=protos" diz ao protoc: "finja que os arquivos de
        # protos/ estão numa pasta chamada gerado/". Com isso o código gerado
        # importa "from gerado import X_pb2" em vez de "import X_pb2", e
        # funciona rodando os serviços a partir da raiz, sem mexer em
        # sys.path. Sem esse truque, o import quebra — é um tropeço clássico
        # de gRPC em Python.
        codigo = protoc.main([
            "grpc_tools.protoc",
            "-Igerado=protos",
            "--python_out=.",
            "--pyi_out=.",
            "--grpc_python_out=.",
            f"protos/{nome}",
        ])
        if codigo != 0:
            print(f"✖ Erro ao gerar {nome} (código {codigo})")
            sys.exit(1)
        print(f"✔ {nome} -> gerado/{nome.replace('.proto', '')}_pb2*.py")


if __name__ == "__main__":
    # Garante que caminhos relativos ("protos/", ".") partam da raiz do
    # projeto, mesmo que o script seja chamado de outra pasta.
    import os
    os.chdir(RAIZ)
    gerar()
