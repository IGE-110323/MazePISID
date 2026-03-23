# PISID 2025/26 — Grupo 35

Sistema de monitorização de labirinto com marsamis em tempo real.

## Arquitetura
```
mazerun.exe → MQTT → mqtt_to_mongo.py → MongoDB
                                              ↓
                                       migration.py → MySQL → PHP → Android
```

## Pré-requisitos

- Python 3.13
- Docker Desktop
- XAMPP (Apache + PHP)
- Android Studio
- MongoDB (Docker)
- MySQL (Docker)

---

## 1. Docker — MongoDB e MySQL

### Iniciar MongoDB
```bash
docker start mongodb
```

### Iniciar MySQL
```bash
docker start mysql
```

> MySQL corre na porta **3307**, MongoDB na porta **27017**.

### Limpar dados (nova sessão)
```bash
docker exec -it mysql mysql -uroot -padmin pisid -e "SET FOREIGN_KEY_CHECKS=0; TRUNCATE TABLE MovementReadings; TRUNCATE TABLE RoomSimulation; TRUNCATE TABLE Corridor; TRUNCATE TABLE Marsami; TRUNCATE TABLE Room; TRUNCATE TABLE Temperature; TRUNCATE TABLE Sound; TRUNCATE TABLE Messages; TRUNCATE TABLE Simulation; SET FOREIGN_KEY_CHECKS=1;"
```

---

## 2. Python — Dependências
```bash
pip install paho-mqtt pymongo mysql-connector-python
```

---

## 3. XAMPP

1. Abre o **XAMPP Control Panel**
2. Inicia o **Apache**
3. Copia a pasta `maze_app_php/` para `C:\xampp\htdocs\`

### Firewall (primeira vez)
Corre no CMD como administrador:
```bash
netsh advfirewall firewall add rule name="Apache HTTP" dir=in action=allow protocol=TCP localport=80
```

---

## 4. Executar o simulador
```bash
mazerun.exe 35 --flagMessage 1 --delay 4 --broker broker.hivemq.com --portbroker 1883
```

> Recomenda-se `--delay 4` para que os gatilhos sejam detetados correctamente.

---

## 5. Executar o pipeline Python

Abre **3 terminais** separados:

**Terminal 1 — MQTT → MongoDB:**
```bash
python mqtt_to_mongo.py
```

**Terminal 2 — MongoDB → MySQL (com deteção de gatilhos):**
```bash
python migration.py
```

> O `migration.py` cria automaticamente uma nova simulação na tabela `Simulation` e só migra dados recebidos após o seu arranque.

---

## 6. App Android

1. Abre o projeto na pasta `Maze/Maze/` com o Android Studio
2. Liga o telemóvel via USB com **Depuração USB** ativada
3. Clica em **Run** (▶)
4. No login da app preenche:
   - **Host:** IP do PC na rede Wi-Fi (corre `ipconfig` e usa o IPv4 da Wi-Fi)
   - **Username:** `admin@maze.com`
   - **Password:** `admin`
   - **Database:** `pisid`

> O telemóvel e o PC têm de estar na **mesma rede Wi-Fi**.

---

## 7. Tópicos MQTT

| Tópico | Descrição |
|--------|-----------|
| `pisid_mazemov_35` | Movimentos dos marsamis |
| `pisid_mazesound_35` | Nível de ruído |
| `pisid_mazetemp_35` | Temperatura |
| `pisid_mazeact` | Gatilhos (Score) |

---

## 8. Limites de dados válidos

| Sensor | Limite máximo |
|--------|--------------|
| Temperatura | 40.0 |
| Som | 40.0 |

Valores acima destes limites são descartados para `dirty_data` no MongoDB.

---

## 9. Estrutura do projeto
```
├── mqtt_to_mongo.py       # Subscreve MQTT e guarda no MongoDB
├── migration.py           # Migra MongoDB → MySQL e deteta gatilhos
├── maze_app_php/          # API REST em PHP para o Android
│   ├── login.php
│   ├── get_temperature_data.php
│   ├── get_sound_data.php
│   ├── get_room_data.php
│   ├── get_messages.php
│   ├── get_max_sound_value.php
│   └── get_min_max_temp_values.php
└── Maze/                  # Projeto Android Studio
    └── Maze/
        └── app/src/main/java/com/maze/
```

---

## Notas

- O `migration.py` ao arrancar marca a simulação anterior como `finished` e cria uma nova — não é necessário limpar a base de dados entre sessões.
- O gatilho `Score` é enviado quando `oddCount == evenCount > 0` numa sala, até um máximo de **3 vezes por sala** por simulação.
- Os PHP usam sempre a simulação com `status = 'active'` mais recente — funcionam automaticamente com novas simulações.
