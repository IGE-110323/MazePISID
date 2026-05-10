import os
import subprocess
import logging
import time
import threading
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import uuid

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL  = 1
WATCHDOG_INTERVAL   = 10
POLL_INTERVAL       = 2
LAUNCH_GRACE_PERIOD = 5

PC_LOCATION = "PC1"

TOPIC_CTRL      = os.getenv("TOPIC_CTRL",      "pisid_internal_35_ctrl")
TOPIC_HEARTBEAT = os.getenv("TOPIC_HEARTBEAT", "pisid_internal_35_heartbeat")

PC1_INPUT_PATH  = os.path.join(os.path.dirname(__file__), "PC1_Input.py")
PC1_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "PC1_Output.py")
SIMULATOR_PATH  = os.getenv("SIMULATOR_PATH", r"C:\mazerun\mazerun.exe")
PLAYER_NUMBER   = os.getenv("PLAYER_NUMBER", "35")

mqtt_client    = None
mqtt_connected = False
last_watchdog  = 0
last_launched  = {}

SERVICES = {
    "pc1_input":  {"path": PC1_INPUT_PATH,  "process": None},
    "pc1_output": {"path": PC1_OUTPUT_PATH, "process": None},
}

mazerun_process = None

# Ficheiro local de config da simulação
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "simulation_config.json")

PIDS_FILE = os.path.join(os.path.dirname(__file__), "pids.json")

def save_pids():
    try:
        pids = {}
        for name, info in SERVICES.items():
            if is_process_alive(info["process"]):
                pids[name] = info["process"].pid
        if is_process_alive(mazerun_process):
            pids["mazerun"] = mazerun_process.pid
        with open(PIDS_FILE, "w") as f:
            json.dump(pids, f)
    except Exception as e:
        log.error(f"Erro ao guardar PIDs: {e}")

def load_pids():
    """Tenta recuperar processos de sessão anterior pelos PIDs guardados"""
    import psutil
    try:
        if not os.path.exists(PIDS_FILE):
            return
        with open(PIDS_FILE, "r") as f:
            pids = json.load(f)
        for name, pid in pids.items():
            if name == "mazerun":
                continue
            try:
                proc = psutil.Process(pid)
                if proc.is_running():
                    SERVICES[name]["process"] = proc
                    last_launched[name] = time.time()
                    log.info(f"PC1_Agent — {name} recuperado (PID {pid})")
            except psutil.NoSuchProcess:
                log.info(f"PC1_Agent — {name} PID {pid} já não existe")
    except Exception as e:
        log.error(f"Erro ao carregar PIDs: {e}")

# ─── Config local ─────────────────────────────────────────────────────────────

def save_simulation_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, default=str)
        log.info(f"PC1_Agent — config simulação guardada: {CONFIG_FILE}")
    except Exception as e:
        log.error(f"Erro ao guardar config: {e}")


def notify_scripts_new_simulation():
    """Escreve um ficheiro de sinalização para os scripts lerem nova config"""
    signal_file = os.path.join(os.path.dirname(__file__), "new_simulation.signal")
    try:
        with open(signal_file, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        log.info("PC1_Agent — sinal de nova simulação escrito")
    except Exception as e:
        log.error(f"Erro ao escrever sinal: {e}")


# ─── Heartbeat agregado ───────────────────────────────────────────────────────

def build_heartbeat_payload():
    """Agrega estado de todos os serviços do PC1 num único payload"""
    services = {}

    for name, info in SERVICES.items():
        services[name] = "online" if is_process_alive(info["process"]) else "offline"

    services["mazerun"] = "online" if is_process_alive(mazerun_process) else "offline"

    return {
        "Type":       "Heartbeat",
        "ServiceName": "pc1_agent",
        "PCLocation":  PC_LOCATION,
        "Timestamp":   datetime.now(timezone.utc).isoformat(),
        "Services":    services
    }


def heartbeat_thread():
    """Publica heartbeat agregado via MQTT a cada 1s"""
    while True:
        if mqtt_connected and mqtt_client:
            try:
                payload = json.dumps(build_heartbeat_payload())
                mqtt_client.publish(TOPIC_HEARTBEAT, payload, qos=1)
            except Exception as e:
                log.error(f"Erro ao publicar heartbeat: {e}")
        else:
            log.warning("PC1_Agent — MQTT indisponível: heartbeat perdido")
        time.sleep(HEARTBEAT_INTERVAL)


# ─── Processos locais ─────────────────────────────────────────────────────────

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


def launch_script(name, path):
    try:
        import platform
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        process = subprocess.Popen(
            ["python", path],
            **kwargs
        )
        log.info(f"PC1_Agent — {name} lançado (PID {process.pid})")
        SERVICES[name]["process"] = process
        last_launched[name] = time.time()
        return process
    except Exception as e:
        log.error(f"Erro ao lançar {name}: {e}")
        return None


def launch_simulator():
    global mazerun_process
    try:
        if not os.path.exists(SIMULATOR_PATH):
            log.warning(f"Simulador não encontrado: {SIMULATOR_PATH}")
            return False
        mazerun_process = subprocess.Popen(
            [SIMULATOR_PATH, PLAYER_NUMBER, "--flagMessage", "1"],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        log.info(f"PC1_Agent — simulador lançado (PID {mazerun_process.pid})")
        last_launched["mazerun"] = time.time()
        return True
    except Exception as e:
        log.error(f"Erro ao lançar simulador: {e}")
        return False


def wait_for_process(name, timeout=LAUNCH_GRACE_PERIOD):
    waited = 0
    while waited < timeout:
        time.sleep(1)
        waited += 1
        if is_process_alive(SERVICES[name]["process"]):
            log.info(f"PC1_Agent — {name} confirmado vivo")
            return True
    log.warning(f"PC1_Agent — {name} não confirmou arranque em {timeout}s")
    return False


# ─── Watchdog ─────────────────────────────────────────────────────────────────

def watchdog_thread():
    while True:
        now = time.time()
        for name, info in SERVICES.items():
            if now - last_launched.get(name, 0) < LAUNCH_GRACE_PERIOD:
                continue
            if not is_process_alive(info["process"]):
                log.warning(f"Watchdog — {name} morreu: a relançar...")
                launch_script(name, info["path"])

        # Mazerun — não relança automaticamente
        if "mazerun" in last_launched and not is_process_alive(mazerun_process):
            log.info("PC1_Agent — mazerun.exe terminou")

        time.sleep(WATCHDOG_INTERVAL)


# ─── Comandos MQTT ────────────────────────────────────────────────────────────

def handle_start_pc1(payload):
    """Recebe config completa do PC2_Agent, guarda localmente e lança scripts"""
    id_command   = payload.get("IDCommand")
    id_simulacao = payload.get("IDSimulacao")
    log.info(f"PC1_Agent — start_pc1: simulação {id_simulacao}")

    # 1. Guardar config localmente
    save_simulation_config(payload)

    # 2. Sinalizar scripts para lerem nova config
    notify_scripts_new_simulation()

    # 3. PC1_Input
    if not is_process_alive(SERVICES["pc1_input"]["process"]):
        log.info("PC1_Agent — PC1_Input offline: a lançar...")
        launch_script("pc1_input", PC1_INPUT_PATH)
        wait_for_process("pc1_input")
    else:
        log.info("PC1_Agent — PC1_Input já está vivo — lerá nova config pelo signal")

    # 4. PC1_Output
    if not is_process_alive(SERVICES["pc1_output"]["process"]):
        log.info("PC1_Agent — PC1_Output offline: a lançar...")
        launch_script("pc1_output", PC1_OUTPUT_PATH)
        wait_for_process("pc1_output")
    else:
        log.info("PC1_Agent — PC1_Output já está vivo — lerá nova config pelo signal")

    # 5. Simulador
    if not is_process_alive(mazerun_process):
        if not launch_simulator():
            log.warning("PC1_Agent — simulador não lançado: lançar manualmente")
    else:
        log.info("PC1_Agent — simulador já está vivo")

    # 6. Notificar PC2_Agent que processou o comando
    if id_command and mqtt_connected:
        try:
            mqtt_client.publish(TOPIC_CTRL, json.dumps({
                "Type":        "CommandProcessed",
                "IDCommand":   id_command,
                "ProcessedBy": "pc1_agent"
            }), qos=1)
            log.info(f"PC1_Agent — CommandProcessed publicado: {id_command}")
        except Exception as e:
            log.error(f"Erro ao publicar CommandProcessed: {e}")


def handle_simulacao_terminada(payload):
    """PC2_Agent notifica que a simulação terminou"""
    sim_id = payload.get("IDSimulacao")
    status = payload.get("Status")
    log.info(f"PC1_Agent — SimulacaoTerminada recebida: {sim_id} (Status={status})")

    # Escreve sinal de fim para PC1_Input e PC1_Output
    signal_file = os.path.join(os.path.dirname(__file__), "simulation_ended.signal")
    try:
        with open(signal_file, "w") as f:
            json.dump({"IDSimulacao": sim_id, "Status": status}, f)
        log.info("PC1_Agent — sinal de fim de simulação escrito")
    except Exception as e:
        log.error(f"Erro ao escrever sinal de fim: {e}")


# ─── MQTT ─────────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_connected
    if reason_code == 0:
        mqtt_connected = True
        client.subscribe(TOPIC_CTRL, qos=1)
        log.info(f"PC1_Agent — MQTT ligado, subscrito: {TOPIC_CTRL}")
    else:
        mqtt_connected = False
        log.error(f"PC1_Agent — falha MQTT: {reason_code}")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    global mqtt_connected
    mqtt_connected = False
    log.warning(f"PC1_Agent — MQTT desligado: {reason_code}")


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        msg_type = payload.get("Type")

        if msg_type == "start_pc1":
            handle_start_pc1(payload)
        elif msg_type == "SimulacaoTerminada":
            handle_simulacao_terminada(payload)
        elif msg_type == "CorridorClosed":
            # Reencaminha para PC1_Input via ficheiro de estado
            _update_corridor_state(payload["RoomA"], payload["RoomB"], closed=True)
        elif msg_type == "CorridorOpened":
            _update_corridor_state(payload["RoomA"], payload["RoomB"], closed=False)

    except Exception as e:
        log.error(f"PC1_Agent — erro MQTT: {e}")


def _update_corridor_state(room_a, room_b, closed):
    """Mantém ficheiro local de corredores fechados para o PC1_Input"""
    corridor_file = os.path.join(os.path.dirname(__file__), "corridor_state.json")
    try:
        if os.path.exists(corridor_file):
            with open(corridor_file, "r") as f:
                state = json.load(f)
        else:
            state = {"closed": []}

        corridor = [room_a, room_b]
        if closed and corridor not in state["closed"]:
            state["closed"].append(corridor)
        elif not closed and corridor in state["closed"]:
            state["closed"].remove(corridor)

        with open(corridor_file, "w") as f:
            json.dump(state, f)

    except Exception as e:
        log.error(f"Erro ao actualizar estado corredores: {e}")


def connect_mqtt():
    global mqtt_client
    broker = os.getenv("MQTT_BROKER", "broker.emqx.io")
    port   = int(os.getenv("MQTT_PORT", 1883))
    try:
        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id = f"pisid_grupo35_pc1_agent_{uuid.uuid4().hex[:8]}",
            clean_session=True
        )
        mqtt_client.on_connect    = on_connect
        mqtt_client.on_disconnect = on_disconnect
        mqtt_client.on_message    = on_message
        mqtt_client.connect(broker, port, keepalive=60)
        mqtt_client.loop_start()
        log.info(f"PC1_Agent — a ligar ao broker {broker}:{port}...")
    except Exception as e:
        log.error(f"Erro ao ligar MQTT: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global last_watchdog

    log.info("A iniciar PC1_Agent...")

    # Recupera processos de sessão anterior
    load_pids()

    # Inicializa grace period para processos não recuperados
    now = time.time()
    for name in SERVICES:
        if last_launched.get(name, 0) == 0:
            last_launched[name] = now

    connect_mqtt()

    threading.Thread(target=heartbeat_thread, daemon=True).start()
    threading.Thread(target=watchdog_thread,  daemon=True).start()

    log.info("PC1_Agent — threads iniciadas. A aguardar comandos MQTT...")

    # Loop principal — apenas mantém o processo vivo
    while True:
        save_pids()  # guarda PIDs a cada ciclo
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
