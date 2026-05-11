import json
import logging
import os
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from config.db import get_mysql_connection
from collections import deque

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ─── Configuração ─────────────────────────────────────────────────────────────
RETRY_INTERVAL         = 5
TIMEOUT                = 120
HEARTBEAT_INTERVAL     = 1
FLUSH_COMPLETE_TIMEOUT = 10  # segundos sem mensagens após fim = flush completo
HEARTBEAT_TIMEOUT          = 10  # agente considera offline após 10s sem heartbeat
last_heartbeat = 0
# ─── Tópicos MQTT distintos por coleção ───────────────────────────────────────
TOPICS = {
    "movements":   os.getenv("TOPIC_DATA_MOV",  "pisid_internal_35_data_mov"),
    "temperature": os.getenv("TOPIC_DATA_TEMP", "pisid_internal_35_data_temp"),
    "sound":       os.getenv("TOPIC_DATA_SND",  "pisid_internal_35_data_snd"),
}

# ─── Buffers locais por coleção ───────────────────────────────────────────────
SCRIPTS_DIR  = os.path.dirname(__file__)
BUFFER_FILES = {
    "movements":   os.path.join(SCRIPTS_DIR, "pc2_buffer_movements.jsonl"),
    "temperature": os.path.join(SCRIPTS_DIR, "pc2_buffer_temperature.jsonl"),
    "sound":       os.path.join(SCRIPTS_DIR, "pc2_buffer_sound.jsonl"),
}
# ─── Estado global ────────────────────────────────────────────────────────────
simulation_id     = None
simulation_config = None

# last_message_time partilhado pelas 3 threads — protegido por lock
_time_lock        = threading.Lock()
last_message_time = time.time()

# Deduplicação independente por coleção — cada thread acede apenas à sua
DEDUP_WINDOW      = 1.0  # segundos
dedup_movements   = deque(maxlen=200)
dedup_temperature = deque(maxlen=200)
dedup_sound       = deque(maxlen=200)

DEDUP = {
    "movements":   dedup_movements,
    "temperature": dedup_temperature,
    "sound":       dedup_sound,
}


# ─── Deduplicação ─────────────────────────────────────────────────────────────

def is_duplicate(collection, document_id):
    """
    Verifica se o document_id já foi processado recentemente.
    Cada coleção tem a sua própria deque — sem contenção entre threads.
    Usa o document_id (ObjectId do MongoDB) como chave — único por documento.
    """
    dedup = DEDUP[collection]
    now   = time.time()
    for cached_id, cached_time in list(dedup):
        if cached_id == document_id and now - cached_time < DEDUP_WINDOW:
            log.warning(f"PC2_Input [{collection}] — duplicado: {document_id}")
            return True
    dedup.append((document_id, now))
    return False

# ─── Buffer local por coleção ─────────────────────────────────────────────────

def save_to_buffer(collection, payload):
    """
    Guarda payload no buffer da coleção em caso de falha MySQL.
    Cada thread escreve apenas no seu próprio ficheiro — sem contenção.
    """
    try:
        entry = json.dumps({"payload": payload}, default=str)
        with open(BUFFER_FILES[collection], "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        log.warning(f"PC2_Input [{collection}] — MySQL indisponível: guardado em buffer")
    except Exception as e:
        log.error(f"Erro ao guardar buffer [{collection}]: {e}")


def flush_buffer(collection):
    """
    Tenta esvaziar o buffer da coleção antes de processar nova mensagem.
    Cada thread chama apenas o seu próprio buffer — sem necessidade de lock.
    Lê tudo, tenta inserir linha a linha, reescreve apenas as que falharam.
    """
    buffer_file = BUFFER_FILES[collection]
    if not os.path.exists(buffer_file):
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
                entry   = json.loads(line.strip())
                payload = entry["payload"]
                _insert_from_payload(collection, payload)
                migrated += 1
            except Exception:
                remaining.append(line)
        with open(buffer_file, "w", encoding="utf-8") as f:
            f.writelines(remaining)
        if migrated > 0:
            log.info(f"PC2_Input [{collection}] — buffer: {migrated} registos migrados")
    except Exception as e:
        log.error(f"Erro ao esvaziar buffer [{collection}]: {e}")


# ─── Inserção no MySQL ────────────────────────────────────────────────────────

def _insert_from_payload(collection, payload):
    """Redireciona para a função de inserção correcta com base na coleção"""
    msg         = payload.get("message")
    received_at = payload.get("received_at")
    document_id = payload.get("document_id")

    if collection == "movements":
        insert_movement(msg, received_at, document_id)
    elif collection == "temperature":
        insert_temperature(msg, received_at, document_id)
    elif collection == "sound":
        insert_sound(msg, received_at, document_id)


def insert_movement(msg, received_at, document_id):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT IGNORE INTO MedicoesPassagens
            (IDSimulacao, IDMarsami, SalaOrigem, SalaDestino,
             Status, Hora, HoraEscrita, IDMedicaoMongo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        simulation_id,
        msg.get("Marsami"),
        msg.get("RoomOrigin") if msg.get("RoomOrigin") != 0 else None,
        msg.get("RoomDestiny"),
        msg.get("Status"),
        received_at,
        datetime.now(timezone.utc),
        document_id
    ))
    conn.commit()
    cursor.close()
    conn.close()
    log.info(f"PC2_Input — movimento: Marsami {msg.get('Marsami')} "
             f"sala {msg.get('RoomOrigin')}→{msg.get('RoomDestiny')}")


def insert_temperature(msg, received_at, document_id):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT IGNORE INTO Temperatura
            (IDSimulacao, Temperatura, Hora, HoraEscrita, IDMedicaoMongo)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        simulation_id,
        msg.get("Temperature"),
        received_at,
        datetime.now(timezone.utc),
        document_id
    ))
    conn.commit()
    cursor.close()
    conn.close()
    log.info(f"PC2_Input — temperatura: {msg.get('Temperature')}")


def insert_sound(msg, received_at, document_id):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT IGNORE INTO Som
            (IDSimulacao, Som, Hora, HoraEscrita, IDMedicaoMongo)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        simulation_id,
        msg.get("Sound"),
        received_at,
        datetime.now(timezone.utc),
        document_id
    ))
    conn.commit()
    cursor.close()
    conn.close()
    log.info(f"PC2_Input — som: {msg.get('Sound')}")


# ─── Heartbeat ────────────────────────────────────────────────────────────────

def register_heartbeat():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.callproc("SP_RegistarHeartbeat", ["pc2_input", "PC2"])
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.error(f"Erro ao registar heartbeat: {e}")


def heartbeat_thread():
    while True:
        register_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)


# ─── Simulação ────────────────────────────────────────────────────────────────

def load_simulation_config():
    global simulation_id, simulation_config
    elapsed = 0
    log.info("PC2_Input — à espera de simulação activa...")
    while True:
        try:
            conn = get_mysql_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.IDSimulacao, sc.Broker, sc.PortBroker, t.PlayerNumber
                FROM Simulacao s
                JOIN SimulationConfig sc ON sc.IDConfig = s.IDConfig
                JOIN Team t ON t.IDTeam = s.IDTeam
                WHERE s.Status = 1
                ORDER BY s.IDSimulacao DESC
                LIMIT 1
            """)
            sim = cursor.fetchone()
            cursor.close()
            conn.close()
            if sim:
                simulation_id     = sim["IDSimulacao"]
                simulation_config = sim
                log.info(f"PC2_Input — simulação activa: {simulation_id}")
                return
            else:
                if elapsed >= TIMEOUT:
                    log.warning(f"Sem simulação activa após {elapsed}s...")
                    elapsed = 0
                time.sleep(RETRY_INTERVAL)
                elapsed += RETRY_INTERVAL
        except Exception as e:
            log.error(f"Erro ao ligar ao MySQL: {e}. Aguardando {RETRY_INTERVAL}s...")
            time.sleep(RETRY_INTERVAL)
            elapsed += RETRY_INTERVAL


def mark_flush_complete():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE Simulacao SET FlushCompleto = 1
            WHERE IDSimulacao = %s AND FlushCompleto = 0
        """, (simulation_id,))
        conn.commit()
        cursor.close()
        conn.close()
        log.info(f"PC2_Input — FlushCompleto=1: simulação {simulation_id}")
    except Exception as e:
        log.error(f"Erro ao marcar FlushCompleto: {e}")


def check_simulation_ended():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT Status, FlushCompleto FROM Simulacao WHERE IDSimulacao = %s",
            (simulation_id,)
        )
        sim = cursor.fetchone()
        cursor.close()
        conn.close()
        if not sim:
            return False
        status         = sim["Status"]
        flush_completo = sim["FlushCompleto"]
        if status in [2, 3, 4]:
            with _time_lock:
                seconds_since_last = time.time() - last_message_time
            if seconds_since_last >= FLUSH_COMPLETE_TIMEOUT:
                if not flush_completo:
                    mark_flush_complete()
                log.info(f"PC2_Input — flush completo: {seconds_since_last:.1f}s sem mensagens")
                return True
        return False
    except Exception as e:
        log.error(f"Erro ao verificar fim de simulação: {e}")
        return False


# ─── MQTT por coleção ─────────────────────────────────────────────────────────

def make_on_connect(collection):
    """Gera on_connect dedicado à coleção — subscreve o tópico correcto"""
    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            topic = TOPICS[collection]
            client.subscribe(topic, qos=1)
            log.info(f"PC2_Input [{collection}] — subscrito: {topic}")
        else:
            log.error(f"PC2_Input [{collection}] — falha MQTT: {reason_code}")
    return on_connect


def make_on_message(collection):
    """
    Gera on_message dedicado à coleção.
    Faz flush do buffer, deduplicação e INSERT MySQL directamente.
    O ACK só é enviado após o callback terminar — atomicidade entre recepção e escrita.
    Em caso de falha MySQL guarda no buffer local.
    """
    def on_message(client, userdata, message):
        global last_message_time
        try:
            payload = json.loads(message.payload.decode())

            if payload.get("Type") != "SensorData":
                return
            if payload.get("simulation_id") != simulation_id:
                return

            # Actualiza timestamp da última mensagem — protegido por lock
            with _time_lock:
                last_message_time = time.time()

            document_id = payload.get("document_id")
            if is_duplicate(collection, document_id):
                return

            # Tenta esvaziar buffer antes de inserir
            flush_buffer(collection)

            # INSERT directo no MySQL — se falhar guarda no buffer
            try:
                _insert_from_payload(collection, payload)
            except Exception as e:
                log.error(f"PC2_Input [{collection}] — erro MySQL: {e}")
                save_to_buffer(collection, payload)

        except json.JSONDecodeError as e:
            log.error(f"PC2_Input [{collection}] — JSON inválido: {e}")
        except Exception as e:
            log.error(f"PC2_Input [{collection}] — erro on_message: {e}")
    return on_message


def create_mqtt_client(collection):
    """
    Cria cliente MQTT dedicado a uma coleção.
    client_id fixo e clean_session=False — broker retém mensagens
    não confirmadas e reenvia em caso de reconexão.
    """
    broker = simulation_config["Broker"]
    port   = simulation_config["PortBroker"]
    connected = threading.Event()

    def on_connect_wrapper(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            connected.set()
        make_on_connect(collection)(client, userdata, flags, reason_code, properties)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"pisid_grupo35_pc2_input_{collection}",
        clean_session=False
    )
    client.on_connect = on_connect_wrapper
    client.on_message = make_on_message(collection)
    client.connect(broker, port, keepalive=60)
    client.loop_start()

    if not connected.wait(timeout=30):
        log.error(f"PC2_Input [{collection}] — timeout MQTT ao ligar")

    return client


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("A iniciar PC2_Input...")

    # Thread de heartbeat — corre para sempre independentemente das simulações
    threading.Thread(target=heartbeat_thread, daemon=True, name="heartbeat").start()

    while True:
        load_simulation_config()

        # Cria 3 clientes MQTT independentes — um por coleção
        clients = {}
        for collection in ["movements", "temperature", "sound"]:
            clients[collection] = create_mqtt_client(collection)

        log.info(f"PC2_Input — 3 clientes MQTT ligados, a aguardar dados...")

        # Aguarda fim de simulação + flush completo
        while True:
            if check_simulation_ended():
                break
            time.sleep(5)

        # Para todos os clientes
        for collection, client in clients.items():
            client.loop_stop()
            client.disconnect()
            log.info(f"PC2_Input [{collection}] — cliente MQTT desligado")

        log.info("PC2_Input — a aguardar nova simulação...")


if __name__ == "__main__":
    main()