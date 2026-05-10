import json
import logging
import os
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
from bson import ObjectId
import paho.mqtt.client as mqtt
from config.db import get_mongo_db
import uuid

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ─── Ficheiros locais ─────────────────────────────────────────────────────────
SCRIPTS_DIR      = os.path.dirname(__file__)
CONFIG_FILE      = os.path.join(SCRIPTS_DIR, "simulation_config.json")
CURSOR_FILE      = os.path.join(SCRIPTS_DIR, "cursor_state.json")
NEW_SIM_SIGNAL   = os.path.join(SCRIPTS_DIR, "new_simulation.signal")
SIM_ENDED_SIGNAL = os.path.join(SCRIPTS_DIR, "simulation_ended.signal")

# ─── Configuração ─────────────────────────────────────────────────────────────
BATCH_SIZE     = 10
POLL_INTERVAL  = 0.5
RETRY_INTERVAL = 2

TOPIC_DATA = os.getenv("TOPIC_DATA", "pisid_internal_35_data")

# ─── Estado global ────────────────────────────────────────────────────────────
simulation_config = None
simulation_id     = None
mqtt_client       = None
mqtt_connected    = False
db                = None

last_signal_mtime = 0


# ─── Ficheiros locais ─────────────────────────────────────────────────────────

def load_simulation_config():
    """Lê config da simulação do ficheiro local escrito pelo PC1_Agent"""
    global simulation_config, simulation_id
    try:
        if not os.path.exists(CONFIG_FILE):
            return False
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            simulation_config = json.load(f)
        simulation_id = simulation_config["IDSimulacao"]
        log.info(f"PC1_Output — config carregada: simulação {simulation_id}")
        return True
    except Exception as e:
        log.error(f"Erro ao ler config: {e}")
        return False


def check_new_simulation_signal():
    """Detecta nova simulação pelo mtime do ficheiro de sinal"""
    global last_signal_mtime
    try:
        if not os.path.exists(NEW_SIM_SIGNAL):
            return False
        mtime = os.path.getmtime(NEW_SIM_SIGNAL)
        if mtime > last_signal_mtime:
            last_signal_mtime = mtime
            log.info("PC1_Output — nova simulação detectada pelo sinal")
            return load_simulation_config()
        return False
    except Exception as e:
        log.error(f"Erro ao verificar sinal: {e}")
        return False


def check_simulation_ended_signal():
    """Verifica se a simulação actual terminou"""
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


# ─── Cursor atómico em ficheiro local ────────────────────────────────────────

def load_cursor():
    """Lê cursor de migração do ficheiro local"""
    try:
        if not os.path.exists(CURSOR_FILE):
            return {}
        with open(CURSOR_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        # Verifica se o cursor é da simulação actual
        if state.get("simulation_id") != simulation_id:
            log.info("PC1_Output — cursor de simulação anterior: a resetar")
            return {}
        return state
    except Exception as e:
        log.error(f"Erro ao ler cursor: {e}")
        return {}


def save_cursor(cursor_state):
    """Persiste cursor de migração no ficheiro local — atomicamente via rename"""
    tmp_file = CURSOR_FILE + ".tmp"
    try:
        cursor_state["simulation_id"] = simulation_id
        cursor_state["updated_at"]    = datetime.now(timezone.utc).isoformat()
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cursor_state, f, indent=2)
        os.replace(tmp_file, CURSOR_FILE)  # atómico no sistema de ficheiros
    except Exception as e:
        log.error(f"Erro ao guardar cursor: {e}")


def get_last_id(cursor_state, collection):
    return cursor_state.get(collection)


def update_cursor_for_collection(cursor_state, collection, last_id):
    cursor_state[collection] = str(last_id)
    save_cursor(cursor_state)


# ─── MQTT ─────────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_connected
    if reason_code == 0:
        mqtt_connected = True
        log.info("PC1_Output — MQTT ligado")
    else:
        mqtt_connected = False
        log.error(f"PC1_Output — falha MQTT: {reason_code}")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    global mqtt_connected
    mqtt_connected = False
    log.warning(f"PC1_Output — MQTT desligado: {reason_code}")


def connect_mqtt():
    global mqtt_client
    broker = simulation_config["Broker"]
    port   = simulation_config["PortBroker"]
    try:
        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id = f"pisid_grupo35_pc1_output_{uuid.uuid4().hex[:8]}",
            clean_session=True
        )
        mqtt_client.on_connect    = on_connect
        mqtt_client.on_disconnect = on_disconnect
        mqtt_client.connect(broker, port, keepalive=60)
        mqtt_client.loop_start()
        log.info(f"PC1_Output — a ligar ao broker {broker}:{port}...")
    except Exception as e:
        log.error(f"Erro ao ligar MQTT: {e}")


# ─── Publicação com cursor atómico ────────────────────────────────────────────

def publish_collection(collection, cursor_state):
    """Lê do MongoDB, publica batch assíncrono no MQTT e actualiza cursor"""
    last_id = get_last_id(cursor_state, collection)

    query = {"simulation_id": simulation_id}
    if last_id:
        query["_id"] = {"$gt": ObjectId(last_id)}

    documents = list(
        db[collection].find(query).sort("_id", 1).limit(BATCH_SIZE)
    )

    if not documents:
        return 0

    # Fase 1 — publica todo o batch sem esperar confirmação individual
    results = []
    for doc in documents:
        try:
            payload = json.dumps({
                "Type":          "SensorData",
                "collection":    collection,
                "simulation_id": simulation_id,
                "document_id":   str(doc["_id"]),
                "message":       doc["message"],
                "received_at":   doc["received_at"].isoformat()
            }, default=str)
            result = mqtt_client.publish(TOPIC_DATA, payload, qos=1)
            results.append((result, doc["_id"]))
        except Exception as e:
            log.error(f"PC1_Output — erro ao publicar {collection} {doc['_id']}: {e}")
            break

    # Fase 2 — aguarda confirmação do batch completo e avança cursor
    published = 0
    for result, doc_id in results:
        try:
            result.wait_for_publish()
            update_cursor_for_collection(cursor_state, collection, doc_id)
            published += 1
        except Exception as e:
            log.error(f"PC1_Output — erro na confirmação {collection} {doc_id}: {e}")
            break

    return published


def has_pending_data(cursor_state):
    """Verifica se ainda há documentos por publicar no MongoDB"""
    for collection in ["movements", "temperature", "sound"]:
        last_id = get_last_id(cursor_state, collection)
        query   = {"simulation_id": simulation_id}
        if last_id:
            query["_id"] = {"$gt": ObjectId(last_id)}
        if db[collection].count_documents(query) > 0:
            return True
    return False


# ─── Loop principal ───────────────────────────────────────────────────────────

def run_simulation(cursor_state):
    """Loop de migração para a simulação activa"""
    log.info(f"PC1_Output — a publicar dados da simulação {simulation_id}...")
    flush_mode = False

    while True:
        # Verifica nova simulação
        if check_new_simulation_signal():
            log.info("PC1_Output — nova simulação detectada: a reiniciar loop")
            return "new_simulation"

        # Verifica fim de simulação
        ended, status = check_simulation_ended_signal()
        if ended and not flush_mode:
            log.info(f"PC1_Output — simulação terminou (Status={status}): modo flush")
            flush_mode = True

        # Publica dados
        cursor_state = load_cursor()  # relê cursor do disco — tolerante a restart
        mov  = publish_collection("movements",   cursor_state)
        temp = publish_collection("temperature", cursor_state)
        snd  = publish_collection("sound",       cursor_state)

        total = mov + temp + snd
        if total > 0:
            label = "flush" if flush_mode else "publicados"
            log.info(f"PC1_Output — {label}: mov={mov}, temp={temp}, som={snd}")

        # Em modo flush — termina quando não há mais dados
        if flush_mode and total == 0:
            if not has_pending_data(cursor_state):
                log.info(f"PC1_Output — flush completo: simulação {simulation_id}")
                return "flush_complete"

        time.sleep(POLL_INTERVAL)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global db, last_signal_mtime

    log.info("A iniciar PC1_Output...")
    db = get_mongo_db()

    # Aguarda config da simulação
    log.info("PC1_Output — à espera de simulation_config.json...")
    while not load_simulation_config():
        time.sleep(2)

    # Inicializa mtime do sinal para não re-processar sinal antigo
    if os.path.exists(NEW_SIM_SIGNAL):
        last_signal_mtime = os.path.getmtime(NEW_SIM_SIGNAL)

    connect_mqtt()

    # Aguarda ligação MQTT
    waited = 0
    while not mqtt_connected and waited < 30:
        time.sleep(1)
        waited += 1
    if not mqtt_connected:
        log.error("PC1_Output — não foi possível ligar ao MQTT em 30s")
        return

    while True:
        # Verifica se há flush pendente de simulação anterior
        cursor_state = load_cursor()
        if cursor_state and cursor_state.get("simulation_id") == simulation_id:
            ended, status = check_simulation_ended_signal()
            if ended:
                log.info(f"PC1_Output — flush pendente detectado: a retomar...")

        result = run_simulation(cursor_state)

        if result == "flush_complete":
            log.info("PC1_Output — a aguardar nova simulação...")
            # Aguarda novo sinal de simulação
            while not check_new_simulation_signal():
                time.sleep(RETRY_INTERVAL)

        elif result == "new_simulation":
            log.info(f"PC1_Output — nova simulação: {simulation_id}")

        connect_mqtt()


if __name__ == "__main__":
    main()
