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

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ─── Ficheiros locais ─────────────────────────────────────────────────────────
SCRIPTS_DIR      = os.path.dirname(__file__)
CONFIG_FILE      = os.path.join(SCRIPTS_DIR, "simulation_config.json")
NEW_SIM_SIGNAL   = os.path.join(SCRIPTS_DIR, "new_simulation.signal")
SIM_ENDED_SIGNAL = os.path.join(SCRIPTS_DIR, "simulation_ended.signal")

# Cursor separado por coleção — sem contenção entre threads
CURSOR_FILES = {
    "movements":   os.path.join(SCRIPTS_DIR, "cursor_movements.json"),
    "temperature": os.path.join(SCRIPTS_DIR, "cursor_temperature.json"),
    "sound":       os.path.join(SCRIPTS_DIR, "cursor_sound.json"),
}

 # ─── Tópicos MQTT distintos por coleção ───────────────────────────────────────
TOPICS = {
    "movements":   os.getenv("TOPIC_DATA_MOV",  "pisid_internal_35_data_mov"),
    "temperature": os.getenv("TOPIC_DATA_TEMP", "pisid_internal_35_data_temp"),
    "sound":       os.getenv("TOPIC_DATA_SND",  "pisid_internal_35_data_snd"),
}

# ─── Configuração ─────────────────────────────────────────────────────────────
POLL_INTERVAL  = 0.5 # segundos entre cada ciclo de polling por thread
RETRY_INTERVAL = 2


# ─── Estado global (protegido por lock onde necessário) ───────────────────────
_config_lock      = threading.RLock()
simulation_config = None
simulation_id     = None
db                = None
last_signal_mtime = 0

# Evento partilhado — activado quando a simulação termina
# Todas as threads detectam simultaneamente sem polling individual
sim_ended_event   = threading.Event()

# Evento partilhado — activado quando nova simulação é detectada
# Todas as threads param o loop actual e reiniciam
new_sim_event     = threading.Event()

# ─── Leitura de Ficheiros locais ─────────────────────────────────────────────────────────

def load_simulation_config():
    """Lê config da simulação do ficheiro local escrito pelo PC1_Agent"""
    global simulation_config, simulation_id
    try:
        if not os.path.exists(CONFIG_FILE):
            return False
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with _config_lock:
            simulation_config = cfg
            simulation_id     = cfg["IDSimulacao"]
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
        with _config_lock:
            sid = simulation_id
        if data.get("IDSimulacao") == sid:
            return True, data.get("Status")
        return False, None
    except Exception as e:
        log.error(f"Erro ao verificar sinal de fim: {e}")
        return False, None


# ─── Cursor atómico por coleção ────────────────────────────────────────

def load_cursor(collection):
    """
    Lê cursor da coleção do seu ficheiro dedicado.
    Cada thread lê apenas o seu próprio ficheiro — sem contenção.
    Verifica se o cursor pertence à simulação actual — reset automático se não.
    """
    cursor_file = CURSOR_FILES[collection]
    try:
        if not os.path.exists(cursor_file):
            return None
        with open(cursor_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        with _config_lock:
            sid = simulation_id
        if state.get("simulation_id") != sid:
            log.info(f"PC1_Output [{collection}] — cursor de simulação anterior: a resetar")
            return None
        return state.get("last_id")
    except Exception as e:
        log.error(f"Erro ao ler cursor [{collection}]: {e}")
        return None


def save_cursor(collection, last_id):
    """
    Persiste cursor da coleção atomicamente via os.replace().
    Cada thread escreve apenas no seu próprio ficheiro — sem lock necessário.
    os.replace() é atómico — nunca deixa o ficheiro corrompido em caso de crash.
    """
    cursor_file = CURSOR_FILES[collection]
    tmp_file    = cursor_file + ".tmp"
    try:
        with _config_lock:
            sid = simulation_id
        state = {
            "simulation_id": sid,
            "last_id":       str(last_id),
            "updated_at":    datetime.now(timezone.utc).isoformat()
        }
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, cursor_file)
    except Exception as e:
        log.error(f"Erro ao guardar cursor [{collection}]: {e}")



# ─── MQTT ─────────────────────────────────────────────────────────────────────

def create_mqtt_client(collection):
    """
    Cria cliente MQTT dedicado a uma coleção.
    client_id fixo por coleção — identificável nos logs do broker.
    clean_session=True — o PC1_Output só publica, não subscreve,
    não precisa de sessão persistente.
    """
    broker = simulation_config["Broker"]
    port   = simulation_config["PortBroker"]
    connected = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            connected.set()
            log.info(f"PC1_Output [{collection}] — MQTT ligado")
        else:
            log.error(f"PC1_Output [{collection}] — falha MQTT: {reason_code}")

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        connected.clear()
        log.warning(f"PC1_Output [{collection}] — MQTT desligado: {reason_code}")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"pisid_grupo35_pc1_output_{collection}",
        clean_session=True
    )
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.connect(broker, port, keepalive=60)
    client.loop_start()

    # Aguarda ligação (máx 30s)
    if not connected.wait(timeout=30):
        log.error(f"PC1_Output [{collection}] — timeout MQTT ao ligar")

    return client


# ─── Publicação assíncrona por batch ──────────────────────────────────────────

def publish_collection(collection, mqtt_client):
    """
    Lê TODOS os documentos novos da coleção desde o último cursor,
    publica em modo assíncrono (batch completo antes de aguardar confirmações)
    e avança o cursor documento a documento após cada PUBACK.

    Retorna o número de documentos publicados com sucesso.
    """
    with _config_lock:
        sid = simulation_id

    last_id = load_cursor(collection)
    topic   = TOPICS[collection]

    query = {"simulation_id": sid}
    if last_id:
        query["_id"] = {"$gt": ObjectId(last_id)}

    # Lê todos os documentos novos — sem limit
    documents = list(db[collection].find(query).sort("_id", 1))

    if not documents:
        return 0

    # Fase 1 — publica todo o batch sem esperar confirmação individual
    results = []
    for doc in documents:
        try:
            payload = json.dumps({
                "Type":          "SensorData",
                "collection":    collection,
                "simulation_id": sid,
                "document_id":   str(doc["_id"]),
                "message":       doc["message"],
                "received_at":   doc["received_at"].isoformat()
            }, default=str)
            result = mqtt_client.publish(topic, payload, qos=1)
            results.append((result, doc["_id"]))
        except Exception as e:
            log.error(f"PC1_Output [{collection}] — erro ao publicar {doc['_id']}: {e}")
            break

    # Fase 2 — aguarda PUBACK e avança cursor documento a documento
    published = 0
    for result, doc_id in results:
        try:
            result.wait_for_publish()
            save_cursor(collection, doc_id)
            published += 1
        except Exception as e:
            log.error(f"PC1_Output [{collection}] — erro na confirmação {doc_id}: {e}")
            break

    return published


def has_pending_data(collection):
    """Verifica se ainda há documentos por publicar na coleção"""
    with _config_lock:
        sid = simulation_id
    last_id = load_cursor(collection)
    query   = {"simulation_id": sid}
    if last_id:
        query["_id"] = {"$gt": ObjectId(last_id)}
    return db[collection].count_documents(query) > 0

# ─── Thread por coleção ───────────────────────────────────────────────────────

def collection_worker(collection):
    """
    Thread dedicada a uma coleção.
    Cria o seu próprio cliente MQTT, lê o seu próprio cursor,
    publica no seu próprio tópico.
    Entra em modo flush quando sim_ended_event é activado.
    Para quando new_sim_event é activado.
    """
    log.info(f"PC1_Output [{collection}] — thread iniciada")

    mqtt_client = create_mqtt_client(collection)
    flush_mode  = False

    while True:
        # Nova simulação detectada — para esta thread
        if new_sim_event.is_set():
            log.info(f"PC1_Output [{collection}] — nova simulação: a parar thread")
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            return

        # Simulação terminou — entra em modo flush
        if sim_ended_event.is_set() and not flush_mode:
            log.info(f"PC1_Output [{collection}] — simulação terminou: modo flush")
            flush_mode = True

        # Publica documentos novos
        published = publish_collection(collection, mqtt_client)

        if published > 0:
            label = "flush" if flush_mode else "publicados"
            log.info(f"PC1_Output [{collection}] — {label}: {published} documentos")

        # Modo flush — termina quando não há mais dados
        if flush_mode and published == 0:
            if not has_pending_data(collection):
                log.info(f"PC1_Output [{collection}] — flush completo")
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
                return

        time.sleep(POLL_INTERVAL)


# ─── Thread de monitorização de sinais ───────────────────────────────────────

def signal_monitor():
    """
    Thread dedicada à verificação de sinais.
    Activa sim_ended_event e new_sim_event para notificar todas as threads
    simultaneamente — sem polling individual em cada thread.
    """
    while True:
        try:
            # Verifica fim de simulação
            if not sim_ended_event.is_set():
                ended, status = check_simulation_ended_signal()
                if ended:
                    log.info(f"PC1_Output — simulação terminou (Status={status}): a notificar threads")
                    sim_ended_event.set()

            # Verifica nova simulação
            if check_new_simulation_signal():
                log.info("PC1_Output — nova simulação detectada: a notificar threads")
                new_sim_event.set()

        except Exception as e:
            log.error(f"Erro no signal_monitor: {e}")

        time.sleep(0.5)


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

        # Arrancar thread de monitorização de sinais
        threading.Thread(
            target=signal_monitor,
            name="signal_monitor",
            daemon=True
        ).start()

    while True:
        # Reset dos eventos para nova simulação
        sim_ended_event.clear()
        new_sim_event.clear()

        # Arrancar 3 threads — uma por coleção
        threads = []
        for collection in ["movements", "temperature", "sound"]:
            t = threading.Thread(
                target=collection_worker,
                args=(collection,),
                name=f"worker_{collection}",
                daemon=True
            )
            t.start()
            threads.append(t)

        # Aguarda que todas as threads terminem
        for t in threads:
            t.join()

        log.info("PC1_Output — todas as threads terminaram")

        # Se foi nova simulação — aguarda config e reinicia
        if new_sim_event.is_set():
            log.info("PC1_Output — a aguardar nova simulação...")
            while not load_simulation_config():
                time.sleep(RETRY_INTERVAL)
            log.info(f"PC1_Output — nova simulação: {simulation_id}")

        # Se foi flush completo — aguarda nova simulação
        else:
            log.info("PC1_Output — flush completo: a aguardar nova simulação...")
            while not check_new_simulation_signal():
                time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
