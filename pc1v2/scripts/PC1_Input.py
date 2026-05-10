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

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ─── Ficheiros locais ─────────────────────────────────────────────────────────
SCRIPTS_DIR        = os.path.dirname(__file__)
CONFIG_FILE        = os.path.join(SCRIPTS_DIR, "simulation_config.json")
CORRIDOR_FILE      = os.path.join(SCRIPTS_DIR, "corridor_state.json")
BUFFER_FILE        = os.path.join(SCRIPTS_DIR, "mongo_buffer.jsonl")
NEW_SIM_SIGNAL     = os.path.join(SCRIPTS_DIR, "new_simulation.signal")
SIM_ENDED_SIGNAL   = os.path.join(SCRIPTS_DIR, "simulation_ended.signal")

# ─── Estado global ────────────────────────────────────────────────────────────
simulation_config  = None
simulation_id      = None
valid_corridors    = set()
closed_corridors   = set()
db                 = None

DEDUP_WINDOW       = 1.0
recent_messages    = deque(maxlen=200)

last_signal_check  = 0
SIGNAL_CHECK_INTERVAL = 0.5  # verifica sinais a cada 2s
STALE_MESSAGE_THRESHOLD = PC1_Agent.WATCHDOG_INTERVAL * 3  # 30s = 3 ciclos de watchdog


# ─── Leitura de ficheiros locais ──────────────────────────────────────────────

def load_simulation_config():
    """Lê config da simulação do ficheiro local escrito pelo PC1_Agent"""
    global simulation_config, simulation_id, valid_corridors, closed_corridors
    try:
        if not os.path.exists(CONFIG_FILE):
            return False
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            simulation_config = json.load(f)
        simulation_id   = simulation_config["IDSimulacao"]
        valid_corridors = {tuple(c) for c in simulation_config.get("Corridors", [])}
        closed_corridors = set()  # nova simulação — todos os corredores abertos
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
    """Verifica se a simulação terminou"""
    try:
        if not os.path.exists(SIM_ENDED_SIGNAL):
            return False, None
        with open(SIM_ENDED_SIGNAL, "r") as f:
            data = json.load(f)
        if data.get("IDSimulacao") == simulation_id:
            return True, data.get("Status")
        return False, None
    except Exception as e:
        log.error(f"Erro ao verificar sinal de fim: {e}")
        return False, None


# ─── Buffer local (fallback MongoDB) ─────────────────────────────────────────

def save_to_buffer(collection, document):
    try:
        entry = json.dumps({"collection": collection, "document": document}, default=str)
        with open(BUFFER_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        log.warning(f"PC1_Input — MongoDB indisponível: guardado em buffer local")
    except Exception as e:
        log.error(f"Erro ao guardar em buffer: {e}")


def flush_buffer():
    if not os.path.exists(BUFFER_FILE):
        return
    try:
        with open(BUFFER_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return
        remaining = []
        migrated  = 0
        for line in lines:
            try:
                entry = json.loads(line.strip())
                if "received_at" in entry["document"]:
                    entry["document"]["received_at"] = datetime.fromisoformat(
                        entry["document"]["received_at"]
                    )
                db[entry["collection"]].insert_one(entry["document"])
                migrated += 1
            except Exception:
                remaining.append(line)
        with open(BUFFER_FILE, "w", encoding="utf-8") as f:
            f.writelines(remaining)
        if migrated > 0:
            log.info(f"PC1_Input — buffer: {migrated} documentos migrados para MongoDB")
    except Exception as e:
        log.error(f"Erro ao esvaziar buffer: {e}")


def insert_mongo(collection, document):
    flush_buffer()
    try:
        db[collection].insert_one(document)
    except Exception as e:
        log.error(f"PC1_Input — MongoDB indisponível: {e}")
        save_to_buffer(collection, document)


# ─── Deduplicação ─────────────────────────────────────────────────────────────

def is_duplicate(msg_type, msg):
    key = f"{msg_type}:{json.dumps(msg, sort_keys=True, default=str)}"
    now = time.time()
    for cached_key, cached_time in list(recent_messages):
        if cached_key == key and now - cached_time < DEDUP_WINDOW:
            log.warning(f"PC1_Input — duplicado: {msg_type}")
            return True
    recent_messages.append((key, now))
    return False


# ─── Validação de dirty data ──────────────────────────────────────────────────

def is_dirty_movement(msg):
    if msg.get("Player") != simulation_config["PlayerNumber"]:
        return True, "invalid_player"
    marsami = msg.get("Marsami")
    max_marsami = simulation_config["NumberMarsamis"]
    max_room = simulation_config["NumberRooms"]
    if not isinstance(marsami, int) or marsami < 1 or marsami > max_marsami:
        return True, "invalid_marsami"
    status = msg.get("Status")
    if status not in [0, 1, 2]:
        return True, "invalid_status"
    room_origin  = msg.get("RoomOrigin")
    room_destiny = msg.get("RoomDestiny")
    if not isinstance(room_origin, int) or not isinstance(room_destiny, int):
        return True, "invalid_room_format"
    if room_origin not in range(0, max_room + 1):
        return True, "invalid_room_origin"
    if room_destiny not in range(0, max_room + 1):
        return True, "invalid_room_destiny"
    if room_origin == 0 and room_destiny == 0:
        if status not in [0, 2]:
            return True, "invalid_stuck_status"
        return False, None
    if room_origin == 0 and room_destiny in range(1, max_room + 1):
        return False, None
    if room_origin == room_destiny and status != 0:
        return True, "invalid_same_room"
    if valid_corridors and (room_origin, room_destiny) not in valid_corridors:
        return True, "invalid_corridor"
    if closed_corridors and (room_origin, room_destiny) in closed_corridors:
        return True, "corridor_closed"
    return False, None


def is_dirty_temperature(msg):
    if msg.get("Player") != simulation_config["PlayerNumber"]:
        return True, "invalid_player"
    try:
        temperature = float(msg.get("Temperature"))
    except (TypeError, ValueError):
        return True, "invalid_temperature_format"
    if temperature < 0:
        return True, "negative_temperature"
    if temperature >= float(simulation_config["ErrorOutlierTemp"]):
        return True, "outlier_temperature"
    hour = msg.get("Hour", "")
    try:
        dt = datetime.strptime(hour, "%Y-%m-%d %H:%M:%S.%f")
        current_year = datetime.now().year
        if dt.year < current_year or dt.year > current_year + 1:
            return True, "invalid_hour_year"
    except (ValueError, TypeError):
        return True, "invalid_hour_format"
    return False, None


def is_dirty_sound(msg):
    if msg.get("Player") != simulation_config["PlayerNumber"]:
        return True, "invalid_player"
    try:
        sound = float(msg.get("Sound"))
    except (TypeError, ValueError):
        return True, "invalid_sound_format"
    if sound < 0:
        return True, "negative_sound"
    if sound >= float(simulation_config["ErrorOutlierSound"]):
        return True, "outlier_sound"
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
    try:
        db["dirty_data"].insert_one({
            "simulation_id":      simulation_id,
            "collection_origin":  collection_origin,
            "reason":             reason,
            "original_message":   original_message,
            "received_at":        datetime.now(timezone.utc)
        })
        log.warning(f"PC1_Input — dirty: {collection_origin} / {reason}")
    except Exception as e:
        log.error(f"Erro ao guardar dirty data: {e}")


# ─── Handlers de mensagens ────────────────────────────────────────────────────

def on_movement(msg):
    dirty, reason = is_dirty_movement(msg)
    if dirty:
        save_dirty("movements", reason, msg)
        return
    insert_mongo("movements", {
        "simulation_id": simulation_id,
        "message":       msg,
        "received_at":   datetime.now(timezone.utc)
    })
    log.info(f"PC1_Input — movimento: Marsami {msg.get('Marsami')} "
             f"sala {msg.get('RoomOrigin')}→{msg.get('RoomDestiny')}")


def on_temperature(msg):
    dirty, reason = is_dirty_temperature(msg)
    if dirty:
        save_dirty("temperature", reason, msg)
        return
    insert_mongo("temperature", {
        "simulation_id": simulation_id,
        "message":       msg,
        "received_at":   datetime.now(timezone.utc)
    })
    log.info(f"PC1_Input — temperatura: {msg.get('Temperature')}")


def on_sound(msg):
    dirty, reason = is_dirty_sound(msg)
    if dirty:
        save_dirty("sound", reason, msg)
        return
    insert_mongo("sound", {
        "simulation_id": simulation_id,
        "message":       msg,
        "received_at":   datetime.now(timezone.utc)
    })
    log.info(f"PC1_Input — som: {msg.get('Sound')}")


# ─── MQTT ─────────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        player = simulation_config["PlayerNumber"]
        topic_mov  = f"{simulation_config['TopicMovement']}{player}"
        topic_snd  = f"{simulation_config['TopicSound']}{player}"
        topic_temp = f"{simulation_config['TopicTemperature']}{player}"
        client.subscribe(topic_mov,  qos=1)
        client.subscribe(topic_snd,  qos=1)
        client.subscribe(topic_temp, qos=1)
        log.info(f"PC1_Input — subscrito: {topic_mov}, {topic_snd}, {topic_temp}")
    else:
        log.error(f"PC1_Input — falha MQTT: {reason_code}")


def on_message(client, userdata, message):
    global last_signal_check

    # Verifica sinais periodicamente dentro do loop MQTT
    now = time.time()
    if now - last_signal_check >= SIGNAL_CHECK_INTERVAL:
        last_signal_check = now
        load_corridor_state()
        check_new_simulation_signal()

    if simulation_config is None:
        return

    try:
        payload = json.loads(message.payload.decode())
        topic   = message.topic
        player  = simulation_config["PlayerNumber"]

        # Determinar collection e msg antes da validação stale
        if f"mazemov_{player}" in topic:
            collection = "movements"
        elif f"mazesound_{player}" in topic:
            collection = "sound"
        elif f"mazetemp_{player}" in topic:
            collection = "temperature"
        else:
            return  # tópico desconhecido

        msg = payload  # mensagem completa para dirty_data

        # Validação stale
        msg_hour = payload.get("Hour")  # no tópico do mazerun é directamente no payload, não em "message"
        if msg_hour:
            msg_time = datetime.fromisoformat(msg_hour)
            age = (datetime.now(timezone.utc) - msg_time.replace(tzinfo=timezone.utc)).total_seconds()
            if age > STALE_MESSAGE_THRESHOLD:
                save_dirty(collection, msg, "stale_message",
                           f"Mensagem com {age:.1f}s de atraso (threshold: {STALE_MESSAGE_THRESHOLD}s)")
                return

        # Processamento normal
        if collection == "movements":
            if not is_duplicate("mov", payload):
                on_movement(payload)
        elif collection == "sound":
            if not is_duplicate("snd", payload):
                on_sound(payload)
        elif collection == "temperature":
            if not is_duplicate("tmp", payload):
                on_temperature(payload)

    except json.JSONDecodeError as e:
        log.error(f"PC1_Input — JSON inválido: {e}")
    except Exception as e:
        log.error(f"PC1_Input — erro ao processar mensagem: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global db, last_signal_check

    log.info("A iniciar PC1_Input...")
    db = get_mongo_db()

    # Aguarda config da simulação
    log.info("PC1_Input — à espera de simulation_config.json...")
    while not load_simulation_config():
        time.sleep(2)

    broker = simulation_config["Broker"]
    port   = simulation_config["PortBroker"]

    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="pisid_grupo35_pc1_input",
        clean_session=False
    )
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    log.info(f"PC1_Input — a ligar ao broker {broker}:{port}...")
    mqtt_client.connect(broker, port, keepalive=60)

    last_signal_check = time.time()

    # loop_forever — o on_message verifica sinais periodicamente
    mqtt_client.loop_forever()


if __name__ == "__main__":
    main()
