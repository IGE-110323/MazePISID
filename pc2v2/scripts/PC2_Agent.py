import os
import subprocess
import logging
import time
import threading
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from config.db import get_mysql_connection
import paho.mqtt.client as mqtt
import psutil
import uuid

PIDS_FILE = os.path.join(os.path.dirname(__file__), "pids_pc2.json")

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL       = 1
HEARTBEAT_TIMEOUT        = 10
WATCHDOG_INTERVAL        = 10
POLL_INTERVAL            = 2
LAUNCH_GRACE_PERIOD      = 20
ABANDONED_CHECK_INTERVAL = 30
ABANDONED_TIMEOUT        = 60
SIM_MONITOR_INTERVAL     = 3  # verifica fim de simulação a cada 3s

PC_LOCATION = "PC2"

TOPIC_DATA      = os.getenv("TOPIC_DATA",      "pisid_internal_35_data")
TOPIC_CTRL      = os.getenv("TOPIC_CTRL",      "pisid_internal_35_ctrl")
TOPIC_HEARTBEAT = os.getenv("TOPIC_HEARTBEAT", "pisid_internal_35_heartbeat")

SCRIPTS = {
    "pc2_input":  os.path.join(os.path.dirname(__file__), "PC2_Input.py"),
    "pc2_output": os.path.join(os.path.dirname(__file__), "PC2_Output.py"),
}

mqtt_client    = None
mqtt_connected = False
last_launched  = {}

SERVICES = {
    "pc2_input":  {"path": SCRIPTS["pc2_input"],  "process": None},
    "pc2_output": {"path": SCRIPTS["pc2_output"], "process": None},
}

# Simulação activa em memória — para evitar queries repetidas
active_simulation_id   = None
simulation_ended_notified = set()  # IDSimulacao já notificados

import psutil


def save_pids():
    try:
        pids = {}
        for name, info in SERVICES.items():
            if is_process_alive(info["process"]):
                pids[name] = info["process"].pid
        with open(PIDS_FILE, "w") as f:
            json.dump(pids, f)
    except Exception as e:
        log.error(f"Erro ao guardar PIDs: {e}")


def load_pids():
    """Recupera processos de sessão anterior pelos PIDs guardados"""
    try:
        if not os.path.exists(PIDS_FILE):
            return
        with open(PIDS_FILE, "r") as f:
            pids = json.load(f)
        for name, pid in pids.items():
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and name in SERVICES:
                    SERVICES[name]["process"] = proc
                    last_launched[name] = time.time()
                    log.info(f"PC2_Agent — {name} recuperado (PID {pid})")
            except psutil.NoSuchProcess:
                log.info(f"PC2_Agent — {name} PID {pid} já não existe")
    except Exception as e:
        log.error(f"Erro ao carregar PIDs: {e}")
# ─── MySQL ────────────────────────────────────────────────────────────────────

def register_heartbeat(service_name, pc_location=PC_LOCATION):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.callproc("SP_RegistarHeartbeat", [service_name, pc_location])
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.error(f"Erro ao registar heartbeat {service_name}: {e}")


def is_process_alive(process):
    if process is None:
        return False
    # subprocess.Popen
    if hasattr(process, 'poll'):
        return process.poll() is None
    # psutil.Process
    if hasattr(process, 'is_running'):
        try:
            return process.is_running() and process.status() != 'zombie'
        except:
            return False
    return False


def is_service_alive(service_name):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TIMESTAMPDIFF(SECOND, LastHeartbeat, UTC_TIMESTAMP()) as elapsed
            FROM ServiceHealth WHERE ServiceName = %s
        """, (service_name,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row or row["elapsed"] is None:
            return False
        return row["elapsed"] < HEARTBEAT_TIMEOUT
    except Exception as e:
        log.error(f"Erro ao verificar {service_name}: {e}")
        return False


def load_simulation_config_for_start(id_simulacao):
    """Carrega config completa da simulação para enviar ao PC1"""
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                s.IDSimulacao,
                t.PlayerNumber,
                sc.Broker, sc.PortBroker,
                sc.TopicMovement, sc.TopicSound,
                sc.TopicTemperature, sc.TopicAction,
                COALESCE(s.ErrorOutlierTemp,  sc.ErrorOutlierTemp)  as ErrorOutlierTemp,
                COALESCE(s.ErrorOutlierSound, sc.ErrorOutlierSound) as ErrorOutlierSound,
                COALESCE(s.TimeMarsamiLive,   sc.TimeMarsamiLive)   as TimeMarsamiLive,
                COALESCE(s.ParamAcLimit,      sc.ParamAcLimit)      as ParamAcLimit,
                m.NormalTemperature, m.TempHighToleration,
                m.TempLowToleration, m.NormalNoise, m.NoiseVarToleration,
                m.NumberMarsamis, m.NumberRooms
            FROM Simulacao s
            JOIN SimulationConfig sc ON sc.IDConfig = s.IDConfig
            JOIN Maze m ON m.IDMaze = sc.IDMaze
            JOIN Team t ON t.IDTeam = s.IDTeam
            WHERE s.IDSimulacao = %s
        """, (id_simulacao,))
        config = cursor.fetchone()

        # Carregar corredores válidos
        cursor.execute("""
            SELECT c.RoomA, c.RoomB
            FROM Corridor c
            JOIN SimulationConfig sc ON sc.IDMaze = c.IDMaze
            JOIN Simulacao s ON s.IDConfig = sc.IDConfig
            WHERE s.IDSimulacao = %s
        """, (id_simulacao,))
        corridors = [[c["RoomA"], c["RoomB"]] for c in cursor.fetchall()]
        cursor.close()
        conn.close()

        if config:
            config["Corridors"] = corridors
        return config

    except Exception as e:
        log.error(f"Erro ao carregar config simulação {id_simulacao}: {e}")
        return None


# ─── Lançamento de Scripts ────────────────────────────────────────────────────

def launch_script(name):
    path = SCRIPTS.get(name)
    if not path:
        return None
    try:
        import platform
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        process = subprocess.Popen(
            ["python", path],
            **kwargs
        )
        log.info(f"PC2_Agent — {name} lançado (PID {process.pid})")
        SERVICES[name]["process"] = process
        last_launched[name] = time.time()
        return process
    except Exception as e:
        log.error(f"Erro ao lançar {name}: {e}")
        return None

# ─── Thread: Heartbeat ────────────────────────────────────────────────────────

def heartbeat_thread():
    while True:
        register_heartbeat("pc2_agent")
        time.sleep(HEARTBEAT_INTERVAL)


# ─── Thread: Watchdog ─────────────────────────────────────────────────────────

def watchdog_thread():
    while True:
        now = time.time()
        for name, info in SERVICES.items():
            if now - last_launched.get(name, 0) < LAUNCH_GRACE_PERIOD:
                continue
            # Verifica por PID local primeiro
            if not is_process_alive(info["process"]):
                log.warning(f"Watchdog — {name} morreu: a relançar...")
                launch_script(name)
                continue
            # Verifica por heartbeat no MySQL
            if not is_service_alive(name):
                log.warning(f"Watchdog — {name} vivo mas sem heartbeat: a relançar...")
                info["process"].terminate()
                launch_script(name)
        time.sleep(WATCHDOG_INTERVAL)


# ─── Thread: Monitor de Simulação ────────────────────────────────────────────

def simulation_monitor_thread():
    """Detecta fim de simulação e notifica PC1 via MQTT"""
    global active_simulation_id
    # Aguarda ligação MQTT antes de começar
    waited = 0
    while not mqtt_connected and waited < 30:
        time.sleep(1)
        waited += 1
    while True:
        try:
            conn = get_mysql_connection()
            cursor = conn.cursor()

            # Detectar simulação activa
            cursor.execute("""
                SELECT IDSimulacao FROM Simulacao
                WHERE Status = 1
                ORDER BY IDSimulacao DESC LIMIT 1
            """)
            active = cursor.fetchone()
            if active:
                active_simulation_id = active["IDSimulacao"]

            # Detectar simulação terminada ainda não notificada
            cursor.execute("""
                SELECT IDSimulacao, Status FROM Simulacao
                WHERE Status IN (2, 3, 4)
                ORDER BY IDSimulacao DESC LIMIT 1
            """)
            ended = cursor.fetchone()
            cursor.close()
            conn.close()

            if ended and ended["IDSimulacao"] not in simulation_ended_notified:
                sim_id = ended["IDSimulacao"]
                status = ended["Status"]
                publish_ctrl({
                    "Type":        "SimulacaoTerminada",
                    "IDSimulacao": sim_id,
                    "Status":      status
                })
                simulation_ended_notified.add(sim_id)
                log.info(f"PC2_Agent — SimulacaoTerminada publicada: {sim_id} (Status={status})")

        except Exception as e:
            log.error(f"Erro no monitor de simulação: {e}")

        time.sleep(SIM_MONITOR_INTERVAL)


# ─── Thread: Simulação Abandonada ────────────────────────────────────────────

def abandoned_thread():
    while True:
        try:
            conn = get_mysql_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.IDSimulacao
                FROM Simulacao s
                WHERE s.Status = 1
                  AND s.DataHoraInicio IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM MedicoesPassagens mp
                    WHERE mp.IDSimulacao = s.IDSimulacao
                      AND mp.HoraEscrita >= UTC_TIMESTAMP() - INTERVAL %s SECOND
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM Temperatura t
                    WHERE t.IDSimulacao = s.IDSimulacao
                      AND t.HoraEscrita >= UTC_TIMESTAMP() - INTERVAL %s SECOND
                  )
                  AND TIMESTAMPDIFF(SECOND, s.DataHoraInicio, UTC_TIMESTAMP()) > %s
            """, (ABANDONED_TIMEOUT, ABANDONED_TIMEOUT, ABANDONED_TIMEOUT))
            abandoned = cursor.fetchone()
            cursor.close()
            conn.close()

            if abandoned:
                sim_id = abandoned["IDSimulacao"]
                log.warning(f"PC2_Agent — simulação {sim_id} abandonada")
                conn2 = get_mysql_connection()
                cursor2 = conn2.cursor()
                cursor2.execute("""
                    UPDATE Simulacao
                    SET Status = 4, DataHoraFim = UTC_TIMESTAMP()
                    WHERE IDSimulacao = %s AND Status = 1
                """, (sim_id,))
                conn2.commit()
                cursor2.close()
                conn2.close()
                log.info(f"PC2_Agent — simulação {sim_id} marcada Status=4")

        except Exception as e:
            log.error(f"Erro ao verificar simulação abandonada: {e}")

        time.sleep(ABANDONED_CHECK_INTERVAL)


# ─── MQTT ─────────────────────────────────────────────────────────────────────

def publish_ctrl(payload):
    if not mqtt_connected or not mqtt_client:
        log.warning(f"PC2_Agent — MQTT indisponível: não foi possível publicar {payload.get('Type')}")
        return
    try:
        mqtt_client.publish(TOPIC_CTRL, json.dumps(payload), qos=1)
        log.info(f"PC2_Agent — publicado ctrl: {payload.get('Type')}")
    except Exception as e:
        log.error(f"Erro ao publicar ctrl: {e}")


def handle_heartbeat_pc1(payload):
    """Desagrega heartbeat do PC1 e persiste todos os serviços no MySQL"""
    pc_location = payload.get("PCLocation", "PC1")

    # Heartbeat do próprio PC1_Agent
    register_heartbeat("pc1_agent", pc_location)

    # Heartbeats dos serviços reportados
    services = payload.get("Services", {})
    for service_name, status in services.items():
        if status == "online":
            register_heartbeat(service_name, pc_location)
            log.debug(f"PC2_Agent — heartbeat proxy: {service_name}@{pc_location}")


def handle_command_processed(payload):
    id_command   = payload.get("IDCommand")
    processed_by = payload.get("ProcessedBy", "pc1_agent")
    if not id_command:
        return
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE CommandQueue
            SET Status = 2, ProcessedAt = UTC_TIMESTAMP(), ProcessedBy = %s
            WHERE IDCommand = %s
        """, (processed_by, id_command))
        conn.commit()
        cursor.close()
        conn.close()
        log.info(f"PC2_Agent — comando {id_command} marcado processado")
    except Exception as e:
        log.error(f"Erro ao marcar comando {id_command}: {e}")


def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_connected
    if reason_code == 0:
        mqtt_connected = True
        client.subscribe(TOPIC_HEARTBEAT, qos=1)
        client.subscribe(TOPIC_CTRL,      qos=1)
        log.info(f"PC2_Agent — MQTT ligado")
    else:
        mqtt_connected = False
        log.error(f"PC2_Agent — falha MQTT: {reason_code}")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    global mqtt_connected
    mqtt_connected = False
    log.warning(f"PC2_Agent — MQTT desligado: {reason_code}")


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        msg_type = payload.get("Type")

        if msg_type == "Heartbeat":
            handle_heartbeat_pc1(payload)
        elif msg_type == "CommandProcessed":
            handle_command_processed(payload)

    except Exception as e:
        log.error(f"PC2_Agent — erro MQTT: {e}")


def connect_mqtt():
    global mqtt_client
    broker = os.getenv("MQTT_BROKER", "broker.emqx.io")
    port   = int(os.getenv("MQTT_PORT", 1883))
    try:
        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id = f"pisid_grupo35_pc2_agent_{uuid.uuid4().hex[:8]}",
            clean_session=True
        )
        mqtt_client.on_connect    = on_connect
        mqtt_client.on_disconnect = on_disconnect
        mqtt_client.on_message    = on_message
        mqtt_client.connect(broker, port, keepalive=60)
        mqtt_client.loop_start()
        log.info(f"PC2_Agent — a ligar ao broker {broker}:{port}...")
    except Exception as e:
        log.error(f"Erro ao ligar MQTT: {e}")


# ─── CommandQueue ─────────────────────────────────────────────────────────────

def get_pending_commands():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT IDCommand, Command, IDSimulacao
            FROM CommandQueue
            WHERE Status = 0
            ORDER BY CreatedAt ASC
            LIMIT 5
        """)
        commands = cursor.fetchall()
        cursor.close()
        conn.close()
        return commands
    except Exception as e:
        log.error(f"Erro ao ler CommandQueue: {e}")
        return []


def mark_command_processing(id_command):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE CommandQueue SET Status = 1
            WHERE IDCommand = %s
        """, (id_command,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.error(f"Erro ao marcar comando: {e}")


def process_start_command(command):
    global active_simulation_id
    id_simulacao = command["IDSimulacao"]
    id_command   = command["IDCommand"]
    log.info(f"PC2_Agent — start: simulação {id_simulacao}")
    mark_command_processing(id_command)
    active_simulation_id = id_simulacao

    # 1. Lançar PC2_Input
    if not is_process_alive(SERVICES["pc2_input"]["process"]):
        log.info("PC2_Agent — PC2_Input offline: a lançar...")
        launch_script("pc2_input")
        time.sleep(3)
    else:
        log.info("PC2_Agent — PC2_Input já está vivo")

    # 2. Lançar PC2_Output
    if not is_process_alive(SERVICES["pc2_output"]["process"]):
        log.info("PC2_Agent — PC2_Output offline: a lançar...")
        launch_script("pc2_output")
        time.sleep(3)
    else:
        log.info("PC2_Agent — PC2_Output já está vivo")

    # 3. Carregar config completa e notificar PC1_Agent via MQTT
    config = load_simulation_config_for_start(id_simulacao)
    if config and mqtt_connected:
        payload = {
            "Type":       "start_pc1",
            "IDCommand":  id_command,
            **{k: (int(v) if isinstance(v, __import__('decimal').Decimal) else v)
               for k, v in config.items()}
        }
        mqtt_client.publish(TOPIC_CTRL, json.dumps(payload), qos=1)
        log.info(f"PC2_Agent — start_pc1 publicado com config completa")
    else:
        log.error("PC2_Agent — não foi possível publicar start_pc1")

def init_ended_simulations():
    """Carrega simulações já terminadas para não as re-notificar no arranque"""
    global simulation_ended_notified
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT IDSimulacao FROM Simulacao
            WHERE Status IN (2, 3, 4)
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        simulation_ended_notified = {row["IDSimulacao"] for row in rows}
        log.info(f"PC2_Agent — {len(simulation_ended_notified)} simulações terminadas carregadas")
    except Exception as e:
        log.error(f"Erro ao inicializar simulações terminadas: {e}")
# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("A iniciar PC2_Agent...")

    # Recupera processos de sessão anterior
    load_pids()

    # Inicializa grace period para evitar watchdog imediato no arranque
    now = time.time()
    for name in SERVICES:
        last_launched[name] = now

    connect_mqtt()

    # Inicializa simulações já terminadas — evita re-notificar no arranque
    init_ended_simulations()

    threading.Thread(target=heartbeat_thread,          daemon=True).start()
    threading.Thread(target=watchdog_thread,           daemon=True).start()
    threading.Thread(target=abandoned_thread,          daemon=True).start()
    threading.Thread(target=simulation_monitor_thread, daemon=True).start()

    log.info("PC2_Agent — threads iniciadas. A monitorizar CommandQueue...")

    while True:
        save_pids()
        commands = get_pending_commands()
        for command in commands:
            if command["Command"] == "start":
                process_start_command(command)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
