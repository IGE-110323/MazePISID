import json
import logging
import os
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from collections import deque
import PC1_Agent
from config.db import get_mongo_db

load_dotenv() #lê o ficheiro .env e carrega as variáveis de ambiente, configuração do broker, etc.

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__) #configura o sistema de logging/mensagens com timestamp, nível e mensagem

# ─── Ficheiros locais ─────────────────────────────────────────────────────────
SCRIPTS_DIR        = os.path.dirname(__file__)
CONFIG_FILE        = os.path.join(SCRIPTS_DIR, "simulation_config.json") # simulation_config.json — config da simulação escrita pelo PC1_Agent
CORRIDOR_FILE      = os.path.join(SCRIPTS_DIR, "corridor_state.json") # corridor_state.json — corredores fechados actualizados pelo PC2_Output via MQTT
NEW_SIM_SIGNAL     = os.path.join(SCRIPTS_DIR, "new_simulation.signal") # new_simulation.signal — ficheiro criado pelo PC1_Agent quando nova simulação arranca
SIM_ENDED_SIGNAL   = os.path.join(SCRIPTS_DIR, "simulation_ended.signal") # simulation_ended.signal — ficheiro criado pelo PC1_Agent quando simulação termina

# Buffer separado por coleção — sem contenção entre threads
# dirty separado por tipo para evitar lock entre threads
BUFFER_FILES = {
    "movements":         os.path.join(SCRIPTS_DIR, "buffer_movements.jsonl"),
    "temperature":       os.path.join(SCRIPTS_DIR, "buffer_temperature.jsonl"),
    "sound":             os.path.join(SCRIPTS_DIR, "buffer_sound.jsonl"),
    "dirty_movements":   os.path.join(SCRIPTS_DIR, "buffer_dirty_movements.jsonl"),
    "dirty_temperature": os.path.join(SCRIPTS_DIR, "buffer_dirty_temperature.jsonl"),
    "dirty_sound":       os.path.join(SCRIPTS_DIR, "buffer_dirty_sound.jsonl"),
}

# ─── Estado global (protegido por lock) ───────────────────────────────────────
_config_lock     = threading.RLock() #Um reentrant lock que permite que a mesma thread adquira o lock várias vezes sem deadlock. Protege os ficheiros que podem ser acedidos por várias threads.
simulation_config  = None
simulation_id      = None
valid_corridors    = set()
closed_corridors   = set()
db                 = None

# ─── Deduplicação por tipo (deque circular independente por coleção) ──────────
DEDUP_WINDOW = 1.0   # janela de 1 segundo — apenas duplicados imediatos de rede (QoS 1)
dedup_movements   = deque(maxlen=200)
dedup_temperature = deque(maxlen=200)
dedup_sound       = deque(maxlen=200)

# ─── Configuração ─────────────────────────────────────────────────────────────
SIGNAL_CHECK_INTERVAL    = 0.5 # intervalo em segundos entre verificações de sinais
STALE_THRESHOLD          = PC1_Agent.WATCHDOG_INTERVAL * 3  # 30s = 3 ciclos de watchdog


# ─── Leitura de ficheiros locais ──────────────────────────────────────────────

def load_simulation_config():
    """Lê config da simulação do ficheiro local escrito pelo PC1_Agent"""
    global simulation_config, simulation_id, valid_corridors, closed_corridors
    try:
        if not os.path.exists(CONFIG_FILE):
            return False
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with _config_lock:
            simulation_config = cfg
            simulation_id     = cfg["IDSimulacao"]
            valid_corridors   = {tuple(c) for c in cfg.get("Corridors", [])}
            closed_corridors  = set()
        log.info(f"PC1_Input — config carregada: simulação {simulation_id}, "
                 f"{len(valid_corridors)} corredores válidos")
        return True
    except Exception as e:
        log.error(f"Erro ao ler config: {e}")
        return False


def load_corridor_state():
    """Lê estado dos corredores fechados do ficheiro local"""
    global closed_corridors
    try:
        if not os.path.exists(CORRIDOR_FILE):
            return
        with open(CORRIDOR_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        with _config_lock:
            closed_corridors = {tuple(c) for c in state.get("closed", [])}
        log.debug(f"PC1_Input — corredores fechados: {len(closed_corridors)}")
    except Exception as e:
        log.error(f"Erro ao ler corridor_state: {e}")


def check_new_simulation_signal():
    """Verifica se há nova simulação — lê novo config se sinal existir"""
    try:
        if not os.path.exists(NEW_SIM_SIGNAL):
            return False
        signal_mtime = os.path.getmtime(NEW_SIM_SIGNAL)
        # Verifica se o sinal é mais recente que a última leitura
        if not hasattr(check_new_simulation_signal, "last_mtime"):
            check_new_simulation_signal.last_mtime = 0
        if signal_mtime > check_new_simulation_signal.last_mtime:
            check_new_simulation_signal.last_mtime = signal_mtime
            log.info("PC1_Input — novo sinal de simulação detectado")
            return load_simulation_config()
        return False
    except Exception as e:
        log.error(f"Erro ao verificar sinal: {e}")
        return False


def check_simulation_ended_signal():
    """Verifica se a simulação terminou via ficheiro de sinal do PC1_Agent"""
    try:
        if not os.path.exists(SIM_ENDED_SIGNAL):
            return False, None
        with open(SIM_ENDED_SIGNAL, "r") as f:
            data = json.load(f)
        with _config_lock:
            sid = simulation_id
        if data.get("IDSimulacao") == sid:
            return True, data.get("Status")
        return False, None
    except Exception as e:
        log.error(f"Erro ao verificar sinal de fim: {e}")
        return False, None

# ─── Thread de monitorização de sinais (independente do MQTT) ────────────────

def signal_monitor():
    """
    Thread dedicada à verificação de sinais — não bloqueia o MQTT.
    Verifica a cada SIGNAL_CHECK_INTERVAL segundos:
    - corridor_state.json — corredores fechados pelo PC2_Output
    - new_simulation.signal — nova simulação iniciada pelo PC1_Agent
    - simulation_ended.signal — simulação terminada pelo PC1_Agent
    """
    while True:
        try:
            load_corridor_state()
            check_new_simulation_signal()
            ended, status = check_simulation_ended_signal()
            if ended:
                log.info(f"PC1_Input — simulação terminou (Status={status})")
        except Exception as e:
            log.error(f"Erro no signal_monitor: {e}")
        time.sleep(SIGNAL_CHECK_INTERVAL)


# ─── Buffer local (fallback MongoDB) ─────────────────────────────────────────

def save_to_buffer(buffer_key, document):
    """Guarda documento no buffer identificado por buffer_key"""
    try:
        buffer_file = BUFFER_FILES.get(buffer_key)
        if not buffer_file:
            log.error(f"Buffer desconhecido: {buffer_key}")
            return
        entry = json.dumps({"document": document}, default=str)
        with open(buffer_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        log.warning(f"PC1_Input — MongoDB indisponível: guardado em buffer [{buffer_key}]")
    except Exception as e:
        log.error(f"Erro ao guardar em buffer [{buffer_key}]: {e}")


def flush_buffer(buffer_key, mongo_collection=None):
    """
    Tenta esvaziar o buffer identificado por buffer_key.
    mongo_collection define onde inserir no MongoDB (pode diferir do buffer_key).
    Cada thread chama apenas o seu próprio buffer — sem necessidade de lock.
    """
    mongo_col   = mongo_collection or buffer_key
    buffer_file = BUFFER_FILES.get(buffer_key)
    if not buffer_file or not os.path.exists(buffer_file):
        return
    try:
        with open(buffer_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return
        remaining = []
        migrated  = 0
        for line in lines:
            try:
                entry = json.loads(line.strip())
                doc   = entry["document"]
                if "received_at" in doc:
                    doc["received_at"] = datetime.fromisoformat(doc["received_at"])
                db[mongo_col].insert_one(doc)
                migrated += 1
            except Exception:
                remaining.append(line)
        with open(buffer_file, "w", encoding="utf-8") as f:
            f.writelines(remaining)
        if migrated > 0:
            log.info(f"PC1_Input — buffer [{buffer_key}]: {migrated} documentos migrados")
    except Exception as e:
        log.error(f"Erro ao esvaziar buffer [{buffer_key}]: {e}")


def insert_mongo(collection, document, buffer_key=None):
    """
    Tenta inserir no MongoDB.
    buffer_key permite especificar um buffer diferente da coleção
    (ex: dirty_movements em vez de dirty_data).
    """
    key = buffer_key or collection
    flush_buffer(key, mongo_collection=collection)
    try:
        db[collection].insert_one(document)
    except Exception as e:
        log.error(f"PC1_Input — MongoDB indisponível [{collection}]: {e}")
        save_to_buffer(key, document)


# ─── Deduplicação por coleção ─────────────────────────────────────────────────

def is_duplicate(dedup_deque, msg_type, msg):
    """
    Verifica se a mensagem é duplicada usando uma janela de 1 segundo.
    Cada coleção tem a sua própria deque — sem contenção entre threads.
    Usa o conteúdo serializado como chave — detecta duplicados tardios
    até 1 segundo após a primeira recepção.
    """
    key = f"{msg_type}:{json.dumps(msg, sort_keys=True, default=str)}"
    now = time.time()
    for cached_key, cached_time in list(dedup_deque):
        if cached_key == key and now - cached_time < DEDUP_WINDOW:
            log.warning(f"PC1_Input — duplicado detectado: {msg_type}")
            return True
    dedup_deque.append((key, now))
    return False

def is_stale(msg, collection):
    """
    Verifica se a mensagem é demasiado antiga (stale).
    Mensagens com mais de STALE_THRESHOLD segundos são rejeitadas.
    """
    hour = msg.get("Hour") or msg.get("Hora")
    if not hour:
        return False
    try:
        msg_time = datetime.fromisoformat(str(hour))
        age = (datetime.now(timezone.utc) - msg_time.replace(tzinfo=timezone.utc)).total_seconds()
        if age > STALE_THRESHOLD:
            log.warning(f"PC1_Input — stale [{collection}]: {age:.1f}s de atraso")
            return True
    except Exception:
        pass
    return False


# ─── Validação de dirty data ──────────────────────────────────────────────────

def is_dirty_movement(msg, cfg, vc, cc):
    """
    Validação de movimentos.
    vc = valid_corridors, cc = closed_corridors
    Recebidos como parâmetro do worker_movements que os lê sob lock.
    """
    if msg.get("Player") != cfg["PlayerNumber"]:
        return True, "invalid_player"
    marsami = msg.get("Marsami")
    if not isinstance(marsami, int) or marsami < 1 or marsami > cfg["NumberMarsamis"]:
        return True, "invalid_marsami"
    status = msg.get("Status")
    if status not in [0, 1, 2]:
        return True, "invalid_status"
    room_origin  = msg.get("RoomOrigin")
    room_destiny = msg.get("RoomDestiny")
    if not isinstance(room_origin, int) or not isinstance(room_destiny, int):
        return True, "invalid_room_format"
    max_room = cfg["NumberRooms"]
    if room_origin not in range(0, max_room + 1):
        return True, "invalid_room_origin"
    if room_destiny not in range(0, max_room + 1):
        return True, "invalid_room_destiny"
    if room_origin == 0 and room_destiny == 0:
        if status not in [0, 2]:
            return True, "invalid_stuck_status"
        return False, None
    if room_origin == 0:
        return False, None
    if room_origin == room_destiny and status != 0:
        return True, "invalid_same_room"
    if vc and (room_origin, room_destiny) not in vc:
        return True, "invalid_corridor"
    if cc and (room_origin, room_destiny) in cc:
        return True, "corridor_closed"
    return False, None


def is_dirty_sensor(msg, cfg, field, outlier_key):
    """Validação comum para temperatura e som"""
    if msg.get("Player") != cfg["PlayerNumber"]:
        return True, "invalid_player"
    try:
        value = float(msg.get(field))
    except (TypeError, ValueError):
        return True, f"invalid_{field.lower()}_format"
    if value < 0:
        return True, f"negative_{field.lower()}"
    if value >= float(cfg[outlier_key]):
        return True, f"outlier_{field.lower()}"
    hour = msg.get("Hour", "")
    try:
        dt = datetime.strptime(hour, "%Y-%m-%d %H:%M:%S.%f")
        current_year = datetime.now().year
        if dt.year < current_year or dt.year > current_year + 1:
            return True, "invalid_hour_year"
    except (ValueError, TypeError):
        return True, "invalid_hour_format"
    return False, None

def save_dirty(collection_origin, reason, original_message):
    """
    Guarda dado anómalo no buffer dirty da coleção de origem.
    Cada thread escreve no seu próprio buffer dirty — sem contenção.
    """
    try:
        dirty_key = f"dirty_{collection_origin}"
        doc = {
            "simulation_id":     simulation_id,
            "collection_origin": collection_origin,
            "reason":            reason,
            "original_message":  original_message,
            "received_at":       datetime.now(timezone.utc)
        }
        insert_mongo("dirty_data", doc, buffer_key=dirty_key)
        log.warning(f"PC1_Input — dirty [{collection_origin}]: {reason}")
    except Exception as e:
        log.error(f"Erro ao guardar dirty data: {e}")

# ─── MQTT ─────────────────────────────────────────────────────────────────────

def on_connect_mov(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        with _config_lock:
            cfg = simulation_config
        if cfg is None:
            return
        topic = f"{cfg['TopicMovement']}{cfg['PlayerNumber']}"
        client.subscribe(topic, qos=1)
        log.info(f"PC1_Input — subscrito: {topic}")
    else:
        log.error(f"PC1_Input — falha MQTT mov: {reason_code}")

def on_connect_temp(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        with _config_lock:
            cfg = simulation_config
        if cfg is None:
            return
        topic = f"{cfg['TopicTemperature']}{cfg['PlayerNumber']}"
        client.subscribe(topic, qos=1)
        log.info(f"PC1_Input — subscrito: {topic}")
    else:
        log.error(f"PC1_Input — falha MQTT temp: {reason_code}")

def on_connect_snd(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        with _config_lock:
            cfg = simulation_config
        if cfg is None:
            return
        topic = f"{cfg['TopicSound']}{cfg['PlayerNumber']}"
        client.subscribe(topic, qos=1)
        log.info(f"PC1_Input — subscrito: {topic}")
    else:
        log.error(f"PC1_Input — falha MQTT snd: {reason_code}")


def on_message_mov(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        with _config_lock:
            cfg = simulation_config
            sid = simulation_id
            vc  = valid_corridors
            cc  = closed_corridors
        if cfg is None:
            return
        if is_duplicate(dedup_movements, "mov", payload):
            return
        if is_stale(payload, "movements"):
            save_dirty("movements", "stale_message", payload)
            return
        dirty, reason = is_dirty_movement(payload, cfg, vc, cc)
        if dirty:
            save_dirty("movements", reason, payload)
        else:
            insert_mongo("movements", {
                "simulation_id": sid,
                "message":       payload,
                "received_at":   datetime.now(timezone.utc)
            })
            log.info(f"PC1_Input — movimento: Marsami {payload.get('Marsami')} "
                     f"sala {payload.get('RoomOrigin')}→{payload.get('RoomDestiny')}")
    except json.JSONDecodeError as e:
        log.error(f"PC1_Input — JSON inválido mov: {e}")
    except Exception as e:
        log.error(f"PC1_Input — erro on_message_mov: {e}")


def on_message_temp(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        with _config_lock:
            cfg = simulation_config
            sid = simulation_id
        if cfg is None:
            return
        if is_duplicate(dedup_temperature, "tmp", payload):
            return
        if is_stale(payload, "temperature"):
            save_dirty("temperature", "stale_message", payload)
            return
        dirty, reason = is_dirty_sensor(payload, cfg, "Temperature", "ErrorOutlierTemp")
        if dirty:
            save_dirty("temperature", reason, payload)
        else:
            insert_mongo("temperature", {
                "simulation_id": sid,
                "message":       payload,
                "received_at":   datetime.now(timezone.utc)
            })
            log.info(f"PC1_Input — temperatura: {payload.get('Temperature')}")
    except json.JSONDecodeError as e:
        log.error(f"PC1_Input — JSON inválido temp: {e}")
    except Exception as e:
        log.error(f"PC1_Input — erro on_message_temp: {e}")


def on_message_snd(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        with _config_lock:
            cfg = simulation_config
            sid = simulation_id
        if cfg is None:
            return
        if is_duplicate(dedup_sound, "snd", payload):
            return
        if is_stale(payload, "sound"):
            save_dirty("sound", "stale_message", payload)
            return
        dirty, reason = is_dirty_sensor(payload, cfg, "Sound", "ErrorOutlierSound")
        if dirty:
            save_dirty("sound", reason, payload)
        else:
            insert_mongo("sound", {
                "simulation_id": sid,
                "message":       payload,
                "received_at":   datetime.now(timezone.utc)
            })
            log.info(f"PC1_Input — som: {payload.get('Sound')}")
    except json.JSONDecodeError as e:
        log.error(f"PC1_Input — JSON inválido snd: {e}")
    except Exception as e:
        log.error(f"PC1_Input — erro on_message_snd: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global db

    log.info("A iniciar PC1_Input...")
    db = get_mongo_db()

    log.info("PC1_Input — à espera de simulation_config.json...")
    while not load_simulation_config():
        time.sleep(2)

    threading.Thread(target=signal_monitor, name="signal_monitor", daemon=True).start()

    with _config_lock:
        broker = simulation_config["Broker"]
        port   = simulation_config["PortBroker"]

    client_mov = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
        client_id="pisid_grupo35_pc1_input_mov", clean_session=False)
    client_mov.on_connect = on_connect_mov
    client_mov.on_message = on_message_mov
    client_mov.connect(broker, port, keepalive=60)
    client_mov.loop_start()

    client_temp = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
        client_id="pisid_grupo35_pc1_input_temp", clean_session=False)
    client_temp.on_connect = on_connect_temp
    client_temp.on_message = on_message_temp
    client_temp.connect(broker, port, keepalive=60)
    client_temp.loop_start()

    client_snd = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
        client_id="pisid_grupo35_pc1_input_snd", clean_session=False)
    client_snd.on_connect = on_connect_snd
    client_snd.on_message = on_message_snd
    client_snd.connect(broker, port, keepalive=60)
    client_snd.loop_start()

    log.info(f"PC1_Input — 3 clientes MQTT ligados a {broker}:{port}")

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
