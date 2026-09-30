# Deploy do Discovery na VPS Hostinger

VPS: `ssh vps` → usuário `marino`, IP `82.112.240.107`, Ubuntu 24.04, Python 3.12.
Destino do código: `/home/marino/grpc`. Porta: `50052`.

## 1. No seu PC: empacotar e enviar o código

No PowerShell, na raiz do projeto (`D:\GRPC`):

```powershell
tar --exclude="*.db*" --exclude="__pycache__" --exclude="fotos_usuarios" -czf discovery.tgz config.py logs.py gerado discovery
scp discovery.tgz vps:~
ssh vps "mkdir -p ~/grpc && tar -xzf ~/discovery.tgz -C ~/grpc && rm ~/discovery.tgz"
Remove-Item discovery.tgz
```

O pacote leva só o que o Discovery precisa: `config.py` (a porta), `logs.py`,
`gerado/` (código dos .proto) e a pasta `discovery/` com as fotos do seed.
O banco local e as fotos de teste ficam de fora, para a VPS começar limpa.

## 2. Na VPS: instalar Python e as dependências

```bash
ssh vps
sudo apt update
sudo apt install -y python3-venv
cd ~/grpc
python3 -m venv .venv
.venv/bin/pip install grpcio==1.84.0 grpcio-health-checking==1.84.0 protobuf==7.36.2
```

Só o gRPC e o Health Check. FastAPI e grpcio-tools não são necessários no
servidor. As versões são as mesmas do seu PC: o código em `gerado/` exige grpcio 1.84 e protobuf 7.35.1 ou superior.

## 3. Na VPS: criar os perfis de seed (uma vez)

```bash
.venv/bin/python -m discovery.seed
```

## 4. Na VPS: abrir a porta 50052

> **Verificado em 30/09/2026:** o `ufw` está desativado (`ENABLED=no`), mas a
> porta 50052 está **bloqueada** vindo da internet. Um servidor de teste
> respondia na própria VPS e dava timeout a partir do PC. O bloqueio está no
> firewall do painel da Hostinger (mais provável) ou no iptables.
> Confira os dois abaixo.

Firewall do Ubuntu (ufw) e iptables:

```bash
sudo ufw status
# Se aparecer "Status: active":
sudo ufw allow 50052/tcp
# Se aparecer "Status: inactive", não precisa fazer nada.

sudo iptables -S INPUT
# Se a política for DROP/REJECT (ou houver regra REJECT no fim), libere:
sudo iptables -I INPUT -p tcp --dport 50052 -j ACCEPT
```

Firewall do painel da Hostinger: em hPanel → VPS → Segurança → Firewall,
se houver uma configuração de firewall **ativa**, adicione uma regra
*Accept / TCP / porta 50052 / origem: any*. Se nenhuma estiver ativa, tudo
já é liberado por padrão.

## 5. Na VPS: rodar em segundo plano com systemd

```bash
sudo cp ~/grpc/discovery/discovery.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now discovery
sudo systemctl status discovery      # deve mostrar "active (running)"
journalctl -u discovery -f           # log ao vivo (Ctrl+C sai só do log)
```

Pode fechar o SSH: o serviço continua rodando e também volta após um reboot.

## 6. No seu PC: testar o acesso (com o proxy DESLIGADO)

Com o proxy ativo, o `Test-NetConnection` responde `True` até para portas
onde nada escuta, e o gRPC falha com `DEADLINE_EXCEEDED`.

```powershell
Test-NetConnection 82.112.240.107 -Port 50052
# Esperado: TcpTestSucceeded : True
```

Depois, em `config.py`, troque `DISCOVERY_HOST = "localhost"` por
`DISCOVERY_HOST = "82.112.240.107"` e rode:

```powershell
python -m discovery.testar_cliente
```

Com isso você vê a mesma saída do teste local, agora vindo da nuvem.

**Se falhar:**
- `UNAVAILABLE`: a porta está bloqueada (passo 4) ou o serviço não está rodando (`systemctl status discovery`).
- `DEADLINE_EXCEEDED`: normalmente é um firewall descartando pacotes em silêncio. Revise o passo 4.

## Atualizar o código depois

Repita o passo 1 e rode `sudo systemctl restart discovery` na VPS.

## Limpar os dados de teste (opcional)

Cada execução do `testar_cliente` cria um "Usuário de Teste". Para zerar
e deixar só os 5 perfis de seed:

```bash
sudo systemctl stop discovery
cd ~/grpc && rm -rf discovery/discovery.db* discovery/fotos_usuarios
.venv/bin/python -m discovery.seed
sudo systemctl start discovery
```
