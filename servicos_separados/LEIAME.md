# Serviços separados: um por pasta

Cada pasta daqui é **independente**: pode ser copiada sozinha para outra
máquina e rodada lá, sem precisar das outras pastas.

| Pasta | Serviço | Porta | Precisa de |
|---|---|---|---|
| `discovery/` | Perfis, fotos, feed e curtidas | 50052 | Python 3.12+ |
| `messaging/` | Chat e lista de conversas | 50053 | Python 3.12+ |
| `gateway/` | Site, API REST/WebSocket, login (Auth, 50051) e painel | 8000 | Python 3.12+ e os endereços dos outros dois |

## Iniciar um a um (Windows)

Em cada pasta há um `iniciar.bat`. Na primeira vez ele cria o ambiente
virtual e instala as dependências sozinho; depois só inicia o serviço.

1. `discovery\iniciar.bat`
2. `messaging\iniciar.bat`
3. `gateway\iniciar.bat` → abrir **http://localhost:8000**
4. (opcional) `gateway\painel.bat`

A ordem não importa: o Gateway reconecta sozinho quando um serviço sobe.
Para derrubar um serviço (demonstração), feche a janela dele ou aperte Ctrl+C.

## Onde o Gateway procura os serviços

O arquivo **`gateway/config.py`** diz onde estão o Discovery e o Messaging:

```python
DISCOVERY_HOST = "82.112.240.107"    # nuvem (VPS)    | "localhost" se estiver no mesmo PC
MESSAGING_HOST = "129.151.186.241"   # nuvem (Oracle) | ou o IP de outro PC da rede
```

Nos `config.py` das pastas `discovery/` e `messaging/`, o serviço usa só a
**porta** (escuta em `0.0.0.0`). Os endereços lá ficam em `"localhost"` de
propósito: é para onde aponta o `testar_cliente` daquela pasta, que assim
testa o serviço da própria máquina, e não o da nuvem.

Detalhes de cada serviço no `LEIAME.md` de cada pasta.
