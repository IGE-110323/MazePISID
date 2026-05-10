# PISID 2025/26 — Grupo 35
## Sistema de Monitorização de Labirinto com Marsamis

---

## Índice

1. [Visão Geral](#visão-geral)
2. [Arquitectura](#arquitectura)
3. [Pré-requisitos](#pré-requisitos)
4. [Instalação](#instalação)
5. [Configuração](#configuração)
6. [Arranque do Sistema](#arranque-do-sistema)
7. [Guia de Utilização](#guia-de-utilização)
8. [App Android](#app-android)
9. [Resolução de Problemas](#resolução-de-problemas)
10. [Referência Rápida](#referência-rápida)

---

## Visão Geral

Sistema distribuído de monitorização de um labirinto com marsamis (robots) em tempo real. Os marsamis circulam pelo labirinto e o sistema deteta quando o número de marsamis pares (`even`) é igual ao número de marsamis ímpares (`odd`) numa sala, acionando um gatilho que atribui pontos ao jogador.

---

## Arquitectura

```
mazerun.exe (Windows)
      │
      │ MQTT (broker.emqx.io)
      ▼
┌─────────────────────────────┐
│         PC1                 │
│  PC1_Agent.py               │
│  PC1_Input.py  → MongoDB    │
│  PC1_Output.py ─────────────┼──► MQTT interno ──────────────┐
│  (pisid-mongo1-v2 :27020)   │                               │
│  (pisid-mongo2-v2 :27021)   │                               │
│  (pisid-mongo3-v2 :27022)   │                               │
└─────────────────────────────┘                               │
                                                              ▼
                                              ┌───────────────────────────────┐
                                              │            PC2                │
                                              │  PC2_Agent.py                 │
                                              │  PC2_Input.py  → MySQL        │
                                              │  PC2_Output.py → Gatilhos     │
                                              │  PHP :9003                    │
                                              │  phpMyAdmin :9002             │
                                              │  (pisid-mysql-v2 :3307)       │
                                              └───────────────────────────────┘
                                                              │
                                                              ▼
                                                       App Android
```

### Tópicos MQTT

| Tópico | Descrição |
|--------|-----------|
| `pisid_mazemov_35` | Movimentos dos marsamis (mazerun → PC1) |
| `pisid_mazesound_35` | Nível de ruído (mazerun → PC1) |
| `pisid_mazetemp_35` | Temperatura (mazerun → PC1) |
| `pisid_mazeact` | Actuadores — Score, AcOn, AcOff, CloseDoor, OpenDoor |
| `pisid_internal_35_data` | Dados MongoDB → PC2 (interno) |
| `pisid_internal_35_ctrl` | Controlo PC1 ↔ PC2 (interno) |
| `pisid_internal_35_heartbeat` | Heartbeats dos serviços (interno) |

---

## Pré-requisitos

### Software obrigatório

| Software | Versão mínima | Download |
|----------|---------------|----------|
| Docker Desktop | Última | https://www.docker.com/products/docker-desktop |
| Python | 3.11+ | https://www.python.org/downloads |
| Android Studio | Última | https://developer.android.com/studio |

### Instalar dependências Python

```cmd
pip install pymongo paho-mqtt python-dotenv pymysql psutil cryptography
```

---

## Instalação

### Estrutura de pastas

```
C:\Users\<user>\Desktop\PISID_v3\
├── pc1v2\
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── requirements.txt
│   └── scripts\
│       ├── PC1_Agent.py
│       ├── PC1_Input.py
│       ├── PC1_Output.py
│       ├── config\
│       │   └── db.py
│       └── .env
├── pc2v2\
│   ├── docker-compose.yml
│   ├── Dockerfile.php
│   ├── Dockerfile.pc2
│   ├── requirements.txt
│   ├── src\
│   │   └── maze_app_php\
│   │       ├── jogo.html
│   │       ├── healthcheck.php
│   │       ├── simulacao.php
│   │       ├── login.php
│   │       └── ...
│   ├── mysql_files\
│   ├── pisid_dump_limpo.sql
│   ├── pisid_sps.sql
│   └── scripts\
│       ├── PC2_Agent.py
│       ├── PC2_Input.py
│       ├── PC2_Output.py
│       ├── config\
│       │   └── db.py
│       └── .env
├── mazerun\
│   └── mazerun.exe
└── watch_and_launch.bat
```

### Passo 1 — Criar a rede Docker

```cmd
docker network create pisid-network
```

### Passo 2 — Arrancar PC1 (MongoDB)

```cmd
cd C:\Users\<user>\Desktop\PISID_v3\pc1v2
docker compose up -d
```

Aguarda 15 segundos para o replica set inicializar.

### Passo 3 — Arrancar PC2 (MySQL + PHP)

```cmd
cd C:\Users\<user>\Desktop\PISID_v3\pc2v2
docker compose up -d
```

### Passo 4 — Importar a base de dados

Aguarda 30 segundos após o MySQL inicializar e corre no CMD (não PowerShell):

```cmd
cd C:\Users\<user>\Desktop\PISID_v3\pc2v2
docker exec -i pisid-mysql-v2 mysql -uroot -ppisid1234 pisid < pisid_dump_limpo.sql
docker exec -i pisid-mysql-v2 mysql -uroot -ppisid1234 pisid < pisid_sps.sql
docker exec -i pisid-mysql-v2 mysql -uroot -ppisid1234 pisid < pisid_routines.sql
```

Confirma que as 21 tabelas foram criadas:

```cmd
docker exec -it pisid-mysql-v2 mysql -uroot -ppisid1234 pisid -e "SHOW TABLES;"
```

### Passo 5 — Criar utilizador de acesso

```cmd
docker exec -it pisid-mysql-v2 mysql -uroot -ppisid1234 pisid -e "INSERT INTO Utilizador (IDTeam, Nome, Email, PasswordHash, Tipo) VALUES (1, 'Admin', 'admin@pisid.pt', 'hash', 'ADM');"
```

### Passo 6 — Abrir firewall (primeira vez)

Corre no CMD como administrador:

```cmd
netsh advfirewall firewall add rule name="PISID PHP" dir=in action=allow protocol=TCP localport=9003
netsh advfirewall firewall add rule name="PISID MongoDB" dir=in action=allow protocol=TCP localport=27020
```

---

## Configuração

### .env do PC1 (`pc1v2/scripts/.env`)

```env
# MongoDB
MONGO_URI=mongodb://localhost:27020/?directConnection=true
MONGO_DB=pisid

# MQTT
MQTT_BROKER=broker.emqx.io
MQTT_PORT=1883

# Tópicos internos
TOPIC_DATA=pisid_internal_35_data
TOPIC_CTRL=pisid_internal_35_ctrl
TOPIC_HEARTBEAT=pisid_internal_35_heartbeat

# Simulador
SIMULATOR_PATH=C:\Users\<user>\Desktop\PISID_v3\mazerun\mazerun.exe
PLAYER_NUMBER=35
MAZERUN_FLAG_MESSAGE=1
CONFIG_ID=1
TEAM_ID=1
USER_ID=1
```

### .env do PC2 (`pc2v2/scripts/.env`)

```env
# MQTT
MQTT_BROKER=broker.emqx.io
MQTT_PORT=1883

# Tópicos internos
TOPIC_DATA=pisid_internal_35_data
TOPIC_CTRL=pisid_internal_35_ctrl
TOPIC_HEARTBEAT=pisid_internal_35_heartbeat

# MySQL
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_USER=root
MYSQL_PASSWORD=pisid1234
MYSQL_DB=pisid
```

### Quando PC1 e PC2 estão em PCs diferentes

No `.env` do PC2 muda `MYSQL_HOST` para `127.0.0.1` (local).  
No `.env` do PC1 não precisas de alterar nada — os dados chegam via MQTT.

Se o MongoDB estiver noutro PC, muda no `.env` do PC1:

```env
MONGO_URI=mongodb://IP_DO_PC1:27020/?directConnection=true
```

---

## Arranque do Sistema

### Ordem de arranque obrigatória

```
1. Docker Desktop
2. docker compose up (PC1 e PC2)
3. python PC1_Agent.py
4. python PC2_Agent.py
5. jogo.html → Criar e Iniciar simulação
6. watch_and_launch.bat (lança mazerun.exe automaticamente)
```

### Passo a passo

**Terminal 1 — PC1:**
```cmd
cd C:\Users\<user>\Desktop\PISID_v3\pc1v2\scripts
python PC1_Agent.py
```

**Terminal 2 — PC2:**
```cmd
cd C:\Users\<user>\Desktop\PISID_v3\pc2v2\scripts
python PC2_Agent.py
```

**Terminal 3 — Watch and Launch:**
```cmd
cd C:\Users\<user>\Desktop\PISID_v3
watch_and_launch.bat
```

---

## Guia de Utilização

### Interface Web — jogo.html

Acede em: `http://127.0.0.1:9003/maze_app_php/jogo.html`

**Campos de ligação:**

| Campo | Valor |
|-------|-------|
| Email | `admin@pisid.pt` |
| Host:Porto PHP | `127.0.0.1:9003` |
| Base de dados | `pisid` |
| MySQL user | `root` |
| MySQL password | `pisid1234` |

**Criar e iniciar uma simulação:**

1. Clica **Ligar** — verifica se todos os serviços estão **online**
2. Escreve uma descrição opcional no campo **Nova Simulação**
3. Clica **▶ Criar e Iniciar**
4. O `watch_and_launch.bat` deteta a simulação e lança o `mazerun.exe` automaticamente
5. Os dados começam a fluir: `mazerun → MQTT → MongoDB → MySQL`

**Estado dos serviços:**

| Serviço | Descrição |
|---------|-----------|
| `pc1_agent` | Watchdog do PC1 |
| `pc1_input` | Recebe dados MQTT e guarda no MongoDB |
| `pc1_output` | Lê MongoDB e envia para PC2 via MQTT |
| `pc2_agent` | Watchdog do PC2 |
| `pc2_input` | Recebe dados e insere no MySQL |
| `pc2_output` | Deteta gatilhos e controla actuadores |
| `mazerun` | Simulador (aparece offline quando parado) |

**Editar parâmetros de uma simulação:**

1. Na tabela **Histórico de Simulações** clica **✏ Editar** numa simulação com estado *Criada*
2. Altera os parâmetros (ParamAcLimit, TimeMarsamiLive, ErrorOutlierTemp, ErrorOutlierSound)
3. Clica **▶ Guardar e Iniciar**

### phpMyAdmin

Acede em: `http://127.0.0.1:9002`

- **Servidor:** `pisid-mysql-v2`
- **Utilizador:** `root`
- **Password:** `pisid1234`

### Verificar dados no MySQL

```cmd
docker exec -it pisid-mysql-v2 mysql -uroot -ppisid1234 pisid -e "SELECT COUNT(*) FROM MedicoesPassagens; SELECT COUNT(*) FROM Temperatura; SELECT COUNT(*) FROM Som; SELECT COUNT(*) FROM TriggerLog;"
```

### Limpar dados entre sessões

```cmd
docker exec -it pisid-mysql-v2 mysql -uroot -ppisid1234 pisid -e "SET FOREIGN_KEY_CHECKS=0; TRUNCATE TABLE MedicoesPassagens; TRUNCATE TABLE Temperatura; TRUNCATE TABLE Som; TRUNCATE TABLE TriggerLog; TRUNCATE TABLE OcupacaoLabirinto; TRUNCATE TABLE OcupacaoLabirintoLog; TRUNCATE TABLE Mensagens; TRUNCATE TABLE CommandQueue; TRUNCATE TABLE CorridorStatus; TRUNCATE TABLE CorridorStatusLog; TRUNCATE TABLE Simulacao; SET FOREIGN_KEY_CHECKS=1;"
```

---

## App Android

### Configuração

1. Abre o projeto em `Maze/Maze/` no Android Studio
2. Liga o telemóvel via USB com **Depuração USB** ativada
3. Clica **Run** (▶)

### Login na app

| Campo | Valor |
|-------|-------|
| Host | `IP_DO_PC:9003` |
| Username | `admin@pisid.pt` |
| Password | qualquer |
| Database | `pisid` |

Para descobrir o IP do PC:
```cmd
ipconfig
```
Usa o **IPv4** da rede **Wi-Fi**.

> O telemóvel e o PC têm de estar na **mesma rede Wi-Fi**.

---

## Resolução de Problemas

### Docker não arranca

Abre o Docker Desktop e espera o ícone ficar verde na barra de tarefas antes de correr os comandos.

### Erro "port already allocated"

```cmd
docker stop $(docker ps -aq)
```
Ou no PowerShell:
```powershell
docker system prune -f
```

### MongoDB "No replica set members available"

O script está a tentar ligar pelos nomes internos do Docker. Verifica o `MONGO_URI` no `.env` do PC1:
```env
MONGO_URI=mongodb://localhost:27020/?directConnection=true
```

### MySQL "Can't connect to MySQL server on 'pisid-mysql'"

O script está a ler um `.env` errado. Verifica que o `load_dotenv` em cada script usa o caminho explícito:
```python
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
```

### App Android erro 404

Verifica se o campo **Host** na app tem a porta incluída: `192.168.1.X:9003`

### Serviços aparecem offline no jogo.html

Os agentes Python não estão a correr. Verifica os terminais do `PC1_Agent.py` e `PC2_Agent.py`.

### Erro "cryptography package is required"

```cmd
pip install cryptography
```

### Remover regras de firewall

```cmd
netsh advfirewall firewall delete rule name="PISID PHP"
netsh advfirewall firewall delete rule name="PISID MongoDB"
```

---

## Referência Rápida

### Portas

| Serviço | Porta |
|---------|-------|
| MongoDB primary | 27020 |
| MongoDB secondary 1 | 27021 |
| MongoDB secondary 2 | 27022 |
| MySQL | 3307 |
| PHP / jogo.html | 9003 |
| phpMyAdmin | 9002 |

### Comandos úteis

**Ver logs em tempo real:**
```cmd
docker logs pisid-pc1-agent -f
docker logs pisid-pc2-agent -f
```

**Ver estado dos containers:**
```cmd
docker ps
```

**Parar tudo:**
```cmd
docker stop pisid-mongo1-v2 pisid-mongo2-v2 pisid-mongo3-v2 pisid-mysql-v2 pisid-php-v2 pisid-phpmyadmin-v2
```

**Reiniciar tudo:**
```cmd
cd C:\Users\<user>\Desktop\PISID_v3\pc1v2 && docker compose up -d
cd C:\Users\<user>\Desktop\PISID_v3\pc2v2 && docker compose up -d
```

**Verificar réplica MongoDB:**
```cmd
docker exec -it pisid-mongo1-v2 mongosh --eval "rs.status().members.forEach(m => print(m.name, m.stateStr))"
```

### Broker MQTT

- **Endereço:** `broker.emqx.io:1883`
- **Player:** 35
- **Grupo:** 35