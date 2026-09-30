# Deploy do Messaging no Oracle Cloud

Servidor: `ssh ubuntu@129.151.186.241` → usuário `ubuntu`, Ubuntu 24.04,
Python 3.12, 1 GB de RAM. Destino do código: `/home/ubuntu/grpc`. Porta: `50053`.

> **Antes de testar do seu PC, desligue o proxy.** Com o proxy ativo, o
> `Test-NetConnection` responde `True` até para portas onde nada escuta, e
> as chamadas gRPC falham com `DEADLINE_EXCEEDED` ou `UNAVAILABLE`.

## 1. No seu PC: empacotar e enviar o código

No PowerShell, na raiz do projeto (`D:\GRPC`):

```powershell
tar --exclude="*.db*" --exclude="__pycache__" -czf messaging.tgz config.py logs.py gerado messaging
scp messaging.tgz ubuntu@129.151.186.241:~
ssh ubuntu@129.151.186.241 "mkdir -p ~/grpc && tar -xzf ~/messaging.tgz -C ~/grpc && rm ~/messaging.tgz"
Remove-Item messaging.tgz
```

## 2. No servidor: dependências

O `python3-venv` já está instalado nesta máquina.

```bash
ssh ubuntu@129.151.186.241
cd ~/grpc
python3 -m venv .venv
.venv/bin/pip install grpcio==1.84.0 grpcio-health-checking==1.84.0 protobuf==7.36.2
```

O Messaging não tem seed: o banco é criado vazio quando o serviço sobe.

## 3. Abrir a porta 50053 (dois lugares!)

No Oracle Cloud, o tráfego passa por **dois firewalls**, e os dois precisam liberar a porta.

> **Verificado em 30/09/2026:** a porta 50053 **já chega aberta** do PC até o
> servidor. Um servidor de teste respondeu a uma requisição vinda da internet.
> A Security List (a) já permite; o passo (b) fica só como garantia para
> reboots.

**a) Security List da rede (no site da Oracle, não no servidor):**
1. Console da Oracle Cloud → menu ☰ → *Networking* → *Virtual Cloud Networks*.
2. Clique na VCN da sua instância → *Subnets* → clique na subnet.
3. Clique na *Security List* (ex.: "Default Security List for ...").
4. *Add Ingress Rules*:
   - Source CIDR: `0.0.0.0/0`
   - IP Protocol: `TCP`
   - Destination Port Range: `50053`
5. *Add Ingress Rules* para salvar.

**b) iptables dentro do servidor.** Hoje a política dele já aceita tudo,
mas as imagens da Oracle costumam recriar regras de bloqueio no boot. Por
garantia:

```bash
sudo iptables -I INPUT -p tcp --dport 50053 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true   # grava para sobreviver a reboot, se disponível
```

## 4. No servidor: rodar em segundo plano com systemd

```bash
sudo cp ~/grpc/messaging/messaging.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now messaging
sudo systemctl status messaging      # deve mostrar "active (running)"
journalctl -u messaging -f           # log ao vivo
```

Teste local no próprio servidor (não depende de firewall nem de proxy):

```bash
cd ~/grpc && .venv/bin/python -m messaging.testar_cliente
```

Se isso passar, o serviço está bom. Se o teste do PC (passo 5) falhar,
o problema está na rede: firewall ou proxy.

## 5. No seu PC: testar o acesso (com o proxy DESLIGADO)

Em `config.py`, troque `MESSAGING_HOST = "localhost"` por
`MESSAGING_HOST = "129.151.186.241"` e rode:

```powershell
python -m messaging.testar_cliente
```

Chat ao vivo pela nuvem, com dois terminais no seu PC:

```powershell
python -m messaging.chat_terminal ana bruno "Ana"
python -m messaging.chat_terminal bruno ana "Bruno"
```

**Se falhar:**
- `DEADLINE_EXCEEDED`: pacote descartado em silêncio. Revise a Security List (3a) e confira o proxy.
- `UNAVAILABLE ... Connection refused`: o serviço não está rodando (`systemctl status messaging`).

## Atualizar o código depois

Repita o passo 1 e rode `sudo systemctl restart messaging` no servidor.
