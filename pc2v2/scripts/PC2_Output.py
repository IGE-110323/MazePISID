import json
import logging
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from config.db import get_mysql_connection
import uuid

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

simulation_id = None
mqtt_client   = None
player_number = None
simulation_config = None

RETRY_INTERVAL             = 5
TIMEOUT                    = 120
HEARTBEAT_INTERVAL         = 1   # thread daemon — 1s
HEARTBEAT_TIMEOUT          = 10  # agente considera offline após 10s sem heartbeat
CHECK_INTERVAL_ACTUATORS   = 1

# Thresholds de decisão
TEMP_AC_ON_THRESHOLD       = 0.70
TEMP_AC_OFF_THRESHOLD      = 0.40
NOISE_CLOSE_THRESHOLD      = 0.70
NOISE_EMERGENCY_THRESHOLD  = 0.90
NOISE_REOPEN_THRESHOLD     = 0.60

# Estado interno
ac_ligado              = False
emergency_close_active = False
valid_corridors        = set()


# ─── Heartbeat ────────────────────────────────────────────────────────────────

def register_heartbeat():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.callproc("SP_RegistarHeartbeat", ["pc2_output", "PC2"])
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.error(f"Erro ao registar heartbeat: {e}")


def heartbeat_thread():
    while True:
        register_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)


# ─── Configuração ─────────────────────────────────────────────────────────────

def load_valid_corridors():
    global valid_corridors
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.RoomA, c.RoomB
            FROM Corridor c
            JOIN SimulationConfig sc ON sc.IDMaze = c.IDMaze
            JOIN Simulacao s ON s.IDConfig = sc.IDConfig
            WHERE s.IDSimulacao = %s
        """, (simulation_id,))
        corridors = cursor.fetchall()
        cursor.close()
        conn.close()
        valid_corridors = {(c["RoomA"], c["RoomB"]) for c in corridors}
        log.info(f"Corredores válidos carregados: {len(valid_corridors)}")
    except Exception as e:
        log.error(f"Erro ao carregar corredores: {e}")


def load_config():
    global player_number, simulation_config, simulation_id
    elapsed = 0
    while True:
        try:
            conn = get_mysql_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.IDSimulacao, t.PlayerNumber,
                       sc.Broker, sc.PortBroker, sc.TopicAction,
                       COALESCE(s.ParamAcLimit, sc.ParamAcLimit) as ParamAcLimit,
                       m.NormalTemperature, m.TempHighToleration, m.TempLowToleration,
                       m.NormalNoise, m.NoiseVarToleration
                FROM Simulacao s
                JOIN SimulationConfig sc ON sc.IDConfig = s.IDConfig
                JOIN Maze m ON m.IDMaze = sc.IDMaze
                JOIN Team t ON t.IDTeam = s.IDTeam
                WHERE s.Status = 1
                ORDER BY s.IDSimulacao DESC
                LIMIT 1
            """)
            simulation_config = cursor.fetchone()
            cursor.close()
            conn.close()

            if simulation_config:
                simulation_id = simulation_config["IDSimulacao"]
                player_number = simulation_config["PlayerNumber"]
                log.info(f"PC2_Output — config carregada: simulação {simulation_id}, player {player_number}")
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


# ─── Publicação MQTT ──────────────────────────────────────────────────────────

def publish(payload):
    topic = simulation_config["TopicAction"]
    parts = []
    for k, v in payload.items():
        parts.append(f"{k}: {v}")
    msg = "{" + ", ".join(parts) + "}"
    mqtt_client.publish(topic, msg)
    log.info(f"PC2_Output — publicado: {msg}")


def publish_ctrl(payload):
    """Publica no tópico de controlo interno para o PC1_Input"""
    topic = f"pisid_internal_35_ctrl"
    mqtt_client.publish(topic, json.dumps(payload), qos=1)
    log.info(f"PC2_Output — ctrl publicado: {payload}")


# ─── Actuadores ───────────────────────────────────────────────────────────────

def send_score(room):
    publish({"Type": "Score", "Player": player_number, "Room": room})


def ac_on():
    global ac_ligado
    if not ac_ligado:
        publish({"Type": "AcOn", "Player": player_number})
        ac_ligado = True
        log.info("PC2_Output — AC ligado")


def ac_off():
    global ac_ligado
    if ac_ligado:
        publish({"Type": "AcOff", "Player": player_number})
        ac_ligado = False
        log.info("PC2_Output — AC desligado")


def close_door(room_a, room_b):
    publish({"Type": "CloseDoor", "Player": player_number,
             "RoomOrigin": room_a, "RoomDestiny": room_b})
    update_corridor_status(room_a, room_b, 0)
    publish_ctrl({"Type": "CorridorClosed", "RoomA": room_a, "RoomB": room_b})


def open_door(room_a, room_b):
    publish({"Type": "OpenDoor", "Player": player_number,
             "RoomOrigin": room_a, "RoomDestiny": room_b})
    update_corridor_status(room_a, room_b, 1)
    publish_ctrl({"Type": "CorridorOpened", "RoomA": room_a, "RoomB": room_b})


def close_all_doors():
    publish({"Type": "CloseAllDoor", "Player": player_number})
    update_all_corridors(0)
    log.info("PC2_Output — todos os corredores fechados")
    for (room_a, room_b) in valid_corridors:
        publish_ctrl({"Type": "CorridorClosed", "RoomA": room_a, "RoomB": room_b})


def open_all_doors():
    publish({"Type": "OpenAllDoor", "Player": player_number})
    update_all_corridors(1)
    for (room_a, room_b) in valid_corridors:
        publish_ctrl({"Type": "CorridorOpened", "RoomA": room_a, "RoomB": room_b})


# ─── Base de Dados ────────────────────────────────────────────────────────────

def update_corridor_status(room_a, room_b, status):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE CorridorStatus cs
            JOIN Corridor c ON c.IDCorridor = cs.IDCorridor
            SET cs.Status = %s
            WHERE cs.IDSimulacao = %s
              AND c.RoomA = %s AND c.RoomB = %s
        """, (status, simulation_id, room_a, room_b))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.error(f"Erro ao actualizar corredor: {e}")


def update_all_corridors(status):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE CorridorStatus SET Status = %s WHERE IDSimulacao = %s
        """, (status, simulation_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.error(f"Erro ao actualizar corredores: {e}")


def fechar_corredores_sala(room):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.RoomA, c.RoomB
            FROM Corridor c
            JOIN CorridorStatus cs ON cs.IDCorridor = c.IDCorridor
            WHERE cs.IDSimulacao = %s AND c.RoomB = %s AND cs.Status = 1
        """, (simulation_id, room))
        corredores = cursor.fetchall()
        cursor.close()
        conn.close()
        for c in corredores:
            close_door(c["RoomA"], c["RoomB"])
            log.info(f"PC2_Output — corredor {c['RoomA']}→{c['RoomB']} fechado (sala {room} esgotada)")
    except Exception as e:
        log.error(f"Erro ao fechar corredores sala {room}: {e}")


def get_pending_triggers():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.IDMensagem, m.Sala
            FROM Mensagens m
            WHERE m.IDSimulacao = %s
              AND m.TipoAlerta = 'ODD_EQUAL_EVEN'
              AND NOT EXISTS (
                SELECT 1 FROM TriggerLog t
                WHERE t.IDSimulacao = m.IDSimulacao
                  AND t.IDRoom = m.Sala
                  AND t.TriggeredAt >= m.Hora
              )
              AND (
                SELECT COUNT(*) FROM TriggerLog t2
                WHERE t2.IDSimulacao = m.IDSimulacao
                  AND t2.IDRoom = m.Sala
              ) < 3
        """, (simulation_id,))
        pending = cursor.fetchall()
        cursor.close()
        conn.close()
        return pending
    except Exception as e:
        log.error(f"Erro ao buscar gatilhos pendentes: {e}")
        return []


def get_trigger_count(room):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total FROM TriggerLog
            WHERE IDSimulacao = %s AND IDRoom = %s
        """, (simulation_id, room))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row["total"] if row else 0
    except Exception as e:
        log.error(f"Erro ao contar gatilhos sala {room}: {e}")
        return 0


def CALL_SP(room):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.callproc("SP_AcionarGatilho", [simulation_id, room])
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.error(f"Erro ao chamar SP_AcionarGatilho: {e}")


def send_score_and_log(room):
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT NumeroMarsamisOdd, NumeroMarsamisEven
            FROM OcupacaoLabirinto
            WHERE IDJogo = %s AND Sala = %s
        """, (simulation_id, room))
        occupancy = cursor.fetchone()
        cursor.close()
        conn.close()
        if not occupancy:
            return None
        CALL_SP(room)       # 1. primeiro verifica e regista
        send_score(room)    # 2. só depois publica MQTT
        return "ok"
    except Exception as e:
        log.error(f"Erro ao acionar gatilho sala {room}: {e}")
        return None


def process_triggers():
    pending = get_pending_triggers()
    for trigger in pending:
        room = trigger["Sala"]
        log.info(f"PC2_Output — gatilho detectado sala {room}")
        result = send_score_and_log(room)
        if result:
            total = get_trigger_count(room)
            if total >= 3:
                log.info(f"PC2_Output — sala {room} esgotada (3 gatilhos)")
                fechar_corredores_sala(room)


# ─── Actuadores ───────────────────────────────────────────────────────────────

def get_last_temperature():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Temperatura FROM Temperatura
            WHERE IDSimulacao = %s
            ORDER BY IDTemperatura DESC LIMIT 1
        """, (simulation_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return float(row["Temperatura"]) if row else None
    except Exception as e:
        log.error(f"Erro ao ler temperatura: {e}")
        return None


def get_last_sound():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Som FROM Som
            WHERE IDSimulacao = %s
            ORDER BY IDSom DESC LIMIT 1
        """, (simulation_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return float(row["Som"]) if row else None
    except Exception as e:
        log.error(f"Erro ao ler som: {e}")
        return None


def get_low_priority_rooms():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.Sala,
                o.NumeroMarsamisOdd,
                o.NumeroMarsamisEven,
                COUNT(t.IDTrigger) as gatilhos_acionados,
                ABS(o.NumeroMarsamisOdd - o.NumeroMarsamisEven) as diferenca
            FROM OcupacaoLabirinto o
            LEFT JOIN TriggerLog t ON t.IDSimulacao = o.IDJogo AND t.IDRoom = o.Sala
            WHERE o.IDJogo = %s
            GROUP BY o.Sala, o.NumeroMarsamisOdd, o.NumeroMarsamisEven
            HAVING gatilhos_acionados < 3
            ORDER BY diferenca DESC, gatilhos_acionados DESC
        """, (simulation_id,))
        rooms = cursor.fetchall()
        cursor.close()
        conn.close()
        return rooms
    except Exception as e:
        log.error(f"Erro ao calcular salas baixa prioridade: {e}")
        return []


def manage_actuators():
    global ac_ligado, emergency_close_active

    temp  = get_last_temperature()
    sound = get_last_sound()

    if temp is None or sound is None:
        return

    temp_max  = float(simulation_config["NormalTemperature"]) + float(simulation_config["TempHighToleration"])
    temp_min  = float(simulation_config["NormalTemperature"]) - float(simulation_config["TempLowToleration"])
    noise_max = float(simulation_config["NormalNoise"]) + float(simulation_config["NoiseVarToleration"])

    temp_ratio  = temp  / temp_max  if temp_max  > 0 else 0
    noise_ratio = sound / noise_max if noise_max > 0 else 0

    # Temperatura
    if temp_ratio >= TEMP_AC_ON_THRESHOLD and not ac_ligado:
        log.info(f"Temperatura {temp:.1f} > {TEMP_AC_ON_THRESHOLD*100:.0f}% — a ligar AC")
        ac_on()
    elif temp_ratio <= TEMP_AC_OFF_THRESHOLD and ac_ligado:
        log.info(f"Temperatura {temp:.1f} < {TEMP_AC_OFF_THRESHOLD*100:.0f}% — a desligar AC")
        ac_off()

    # Ruído — circuit breaker
    if noise_ratio >= NOISE_EMERGENCY_THRESHOLD and not emergency_close_active:
        log.warning(f"Ruído {sound:.1f} > 90% — CIRCUIT BREAKER")
        close_all_doors()
        ac_on()
        emergency_close_active = True
    elif noise_ratio <= NOISE_REOPEN_THRESHOLD and emergency_close_active:
        log.info(f"Ruído {sound:.1f} < 60% — a reabrir corredores")
        open_all_doors()
        ac_off()
        emergency_close_active = False
    elif noise_ratio >= NOISE_CLOSE_THRESHOLD and not emergency_close_active:
        rooms = get_low_priority_rooms()
        if rooms:
            worst_room = rooms[-1]
            conn = get_mysql_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.RoomA, c.RoomB
                FROM Corridor c
                JOIN CorridorStatus cs ON cs.IDCorridor = c.IDCorridor
                WHERE cs.IDSimulacao = %s AND c.RoomB = %s AND cs.Status = 1
                LIMIT 1
            """, (simulation_id, worst_room["Sala"]))
            corridor = cursor.fetchone()
            cursor.close()
            conn.close()
            if corridor:
                log.info(f"Ruído > 70% — fechando corredor {corridor['RoomA']}→{corridor['RoomB']}")
                close_door(corridor["RoomA"], corridor["RoomB"])


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global mqtt_client, simulation_id, ac_ligado, emergency_close_active

    log.info("A iniciar PC2_Output...")

    # Thread de heartbeat independente — daemon, morre com o processo
    hb = threading.Thread(target=heartbeat_thread, daemon=True)
    hb.start()

    while True:
        # Reset estado para nova simulação
        ac_ligado = False
        emergency_close_active = False

        load_config()
        load_valid_corridors()

        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"pisid_grupo35_pc2_agent_{uuid.uuid4().hex[:8]}",
            clean_session=True
        )
        mqtt_client.connect(
            simulation_config["Broker"],
            simulation_config["PortBroker"],
            keepalive=60
        )
        mqtt_client.loop_start()

        log.info("PC2_Output — a monitorizar gatilhos e actuadores...")

        last_actuator_check = 0

        while True:
            try:
                now = time.time()

                # Verificar estado da simulação
                conn = get_mysql_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT Status FROM Simulacao WHERE IDSimulacao = %s",
                    (simulation_id,)
                )
                sim = cursor.fetchone()
                cursor.close()
                conn.close()

                if sim and sim["Status"] != 1:
                    log.info(f"PC2_Output — simulação {simulation_id} terminou. Flush de gatilhos...")
                    max_attempts = 10
                    for attempt in range(max_attempts):
                        pending = get_pending_triggers()
                        if not pending:
                            log.info(f"PC2_Output — flush completo em {attempt+1} ciclos")
                            break
                        process_triggers()
                        time.sleep(1)
                    else:
                        log.warning("PC2_Output — timeout no flush de gatilhos")
                    break

                # Processar gatilhos odd=even
                process_triggers()

                # Gestão de actuadores a cada 2s
                if now - last_actuator_check >= CHECK_INTERVAL_ACTUATORS:
                    manage_actuators()
                    last_actuator_check = now

            except Exception as e:
                log.error(f"Erro no ciclo principal: {e}")

            time.sleep(0.5)

        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        log.info("PC2_Output — a aguardar nova simulação...")
        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
