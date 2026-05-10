import json
import logging
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from config.db import get_mysql_connection
from collections import deque
import uuid
import queue

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

simulation_id = None
simulation_config = None

RETRY_INTERVAL = 5
TIMEOUT = 120
HEARTBEAT_INTERVAL         = 1   # thread daemon — 1s
HEARTBEAT_TIMEOUT          = 10  # agente considera offline após 10s sem heartbeat
TOPIC_DATA = "pisid_internal_35_data"

last_heartbeat = 0

recent_ids = deque(maxlen=50)

last_message_time = time.time()
FLUSH_COMPLETE_TIMEOUT = 10  # segundos sem mensagens após fim = flush completo

# ─── Fila de mensagens para thread consumidora ────────────────────────────────
message_queue = queue.Queue()

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
        log.info(f"PC2_Input — FlushCompleto=1 marcado: simulação {simulation_id}")
    except Exception as e:
        log.error(f"Erro ao marcar FlushCompleto: {e}")

def is_duplicate_message(document_id):
    if document_id in recent_ids:
        log.warning(f"PC2_Input — duplicado detectado: {document_id}")
        return True
    recent_ids.append(document_id)
    return False

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
                simulation_id = sim["IDSimulacao"]
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


# ─── Inserção no MySQL ────────────────────────────────────────────────────────

def insert_movement(msg, received_at, document_id):
    try:
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
        log.info(f"PC2_Input — movimento inserido: Marsami {msg.get('Marsami')} "
                 f"sala {msg.get('RoomOrigin')}→{msg.get('RoomDestiny')}")
    except Exception as e:
        log.error(f"Erro ao inserir movimento: {e}")


def insert_temperature(msg, received_at, document_id):
    try:
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
    except Exception as e:
        log.error(f"Erro ao inserir temperatura: {e}")


def insert_sound(msg, received_at, document_id):
    try:
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
    except Exception as e:
        log.error(f"Erro ao inserir som: {e}")


# ─── MQTT ─────────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(TOPIC_DATA, qos=1)
        log.info(f"PC2_Input — subscrito: {TOPIC_DATA}")
    else:
        log.error(f"PC2_Input — falha na ligação MQTT: {reason_code}")


def on_message(client, userdata, message):
    global last_message_time
    try:
        payload = json.loads(message.payload.decode())

        if payload.get("Type") != "SensorData":
            return

        if payload.get("simulation_id") != simulation_id:
            return

        last_message_time = time.time()

        document_id = payload.get("document_id")

        # Deduplicação em memória antes de entrar na fila
        if is_duplicate_message(document_id):
            return

        # Coloca na fila — não bloqueia o callback MQTT
        message_queue.put(payload)

    except json.JSONDecodeError as e:
        log.error(f"PC2_Input — JSON inválido: {e}")
    except Exception as e:
        log.error(f"PC2_Input — erro ao processar mensagem: {e}")


def consumer_thread():
    """Thread consumidora — drena a fila e insere no MySQL imediatamente"""
    while True:
        try:
            payload = message_queue.get(timeout=1)

            collection  = payload.get("collection")
            msg         = payload.get("message")
            received_at = payload.get("received_at")
            document_id = payload.get("document_id")

            if collection == "movements":
                insert_movement(msg, received_at, document_id)
            elif collection == "temperature":
                insert_temperature(msg, received_at, document_id)
            elif collection == "sound":
                insert_sound(msg, received_at, document_id)

            message_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            log.error(f"PC2_Input consumer — erro: {e}")


def check_simulation_ended():
    global last_message_time
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

        status = sim["Status"]
        flush_completo = sim["FlushCompleto"]

        if status in [2, 3, 4]:
            # Simulação terminou — aguarda timeout sem mensagens
            seconds_since_last = time.time() - last_message_time
            if seconds_since_last >= FLUSH_COMPLETE_TIMEOUT:
                if not flush_completo:
                    mark_flush_complete()
                log.info(f"PC2_Input — flush completo confirmado: {seconds_since_last:.1f}s sem mensagens")
                return True

        return False

    except Exception as e:
        log.error(f"Erro ao verificar fim de simulação: {e}")
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global simulation_id

    log.info("A iniciar PC2_Input...")

    # Thread de heartbeat independente
    hb = threading.Thread(target=heartbeat_thread, daemon=True)
    hb.start()

    # Thread consumidora da fila de mensagens
    consumer = threading.Thread(target=consumer_thread, daemon=True)
    consumer.start()

    while True:
        load_simulation_config()

        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id = f"pisid_grupo35_pc2_input_{uuid.uuid4().hex[:8]}",
            clean_session=True
        )
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message

        broker = simulation_config["Broker"]
        port = simulation_config["PortBroker"]

        log.info(f"PC2_Input — a ligar ao broker {broker}:{port}...")
        mqtt_client.connect(broker, port, keepalive=60)
        mqtt_client.loop_start()

        # Aguarda fim de simulação + flush completo
        while True:
            if check_simulation_ended():
                break
            time.sleep(5)

        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        log.info("PC2_Input — a aguardar nova simulação...")


if __name__ == "__main__":
    main()
