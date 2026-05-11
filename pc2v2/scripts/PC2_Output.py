import json
import logging
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from config.db import get_mysql_connection

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ─── Configuração ─────────────────────────────────────────────────────────────
RETRY_INTERVAL           = 5    # segundos entre tentativas de ligação ao MySQL
TIMEOUT                  = 120  # segundos máximos à espera de simulação activa
HEARTBEAT_INTERVAL       = 1    # heartbeat a cada 1 segundo
HEARTBEAT_TIMEOUT        = 10   # agente considera offline após 10s sem heartbeat
CHECK_INTERVAL_ACTUATORS = 1    # gestão de actuadores a cada 1 segundo

# Thresholds de decisão para actuadores — expressos como rácio do valor máximo
# Ex: NOISE_CLOSE_THRESHOLD = 0.70 significa 70% do limite máximo de ruído
TEMP_AC_ON_THRESHOLD      = 0.70  # liga AC quando temperatura > 70% do máximo
TEMP_AC_OFF_THRESHOLD     = 0.40  # desliga AC quando temperatura < 40% do máximo
NOISE_CLOSE_THRESHOLD     = 0.70  # fecha corredor de baixa prioridade quando ruído > 70%
NOISE_EMERGENCY_THRESHOLD = 0.90  # circuit breaker — fecha tudo quando ruído > 90%
NOISE_REOPEN_THRESHOLD    = 0.60  # reabre corredores quando ruído volta abaixo de 60%

# ─── Estado global da simulação ───────────────────────────────────────────────
# Reiniciado a cada nova simulação no main()
simulation_id     = None
simulation_config = None
player_number     = None
mqtt_client       = None

# Estado dos actuadores — reflecte o estado actual do labirinto
ac_ligado              = False  # True se o AC está ligado
emergency_close_active = False  # True se o circuit breaker está activo
valid_corridors        = set()  # conjunto de (RoomA, RoomB) válidos para esta simulação

# Evento partilhado entre threads — sem polling individual ao MySQL
# Activado pelo simulation_monitor quando a simulação termina.
# As threads de gatilhos e actuadores verificam is_set() no início de cada ciclo.
sim_ended_event = threading.Event()

# ─── Heartbeat ────────────────────────────────────────────────────────────────
# Thread daemon independente — regista presença do serviço no MySQL a cada 1s.
# O PC2_Agent monitoriza ServiceHealth e considera o serviço offline
# se não houver heartbeat há mais de HEARTBEAT_TIMEOUT segundos.

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


# ─── Carregamento de configuração ─────────────────────────────────────────────
# Aguarda até existir uma simulação activa (Status=1) no MySQL.
# Lê configuração da simulação, do labirinto e da equipa numa única query
# para evitar múltiplas idas à base de dados no arranque.

def load_config():
    global player_number, simulation_config, simulation_id
    elapsed = 0
    log.info("PC2_Output — à espera de simulação activa...")
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
                log.info(f"PC2_Output — simulação activa: {simulation_id}, player {player_number}")
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


def load_valid_corridors():
    """
    Carrega os corredores válidos do labirinto para esta simulação.
    Usado para saber quais corredores notificar ao PC1_Input via publish_ctrl.
    """
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
        log.info(f"PC2_Output — {len(valid_corridors)} corredores válidos carregados")
    except Exception as e:
        log.error(f"Erro ao carregar corredores: {e}")


# ─── Publicação MQTT ──────────────────────────────────────────────────────────
# Dois tipos de publicação:
# 1. publish() — publica no TopicAction do mazerun (comandos ao simulador)
# 2. publish_ctrl() — publica no tópico interno para o PC1_Agent
#    que actualiza o corridor_state.json lido pelo PC1_Input

def publish(payload):
    """
    Publica comando no tópico do mazerun (TopicAction).
    Formato: {Type: X, Player: Y, ...} em string sem JSON formal
    porque o mazerun espera este formato específico.
    """
    topic = simulation_config["TopicAction"]
    parts = [f"{k}: {v}" for k, v in payload.items()]
    msg   = "{" + ", ".join(parts) + "}"
    mqtt_client.publish(topic, msg)
    log.info(f"PC2_Output — publicado: {msg}")



def publish_ctrl(payload):
    """
    Publica no tópico de controlo interno pisid_internal_35_ctrl.
    O PC1_Agent subscreve este tópico e actualiza o corridor_state.json.
    O PC1_Input lê esse ficheiro a cada 0.5s para saber quais corredores estão fechados
    e rejeitar movimentos através deles como dados anómalos.
    """
    topic = "pisid_internal_35_ctrl"
    mqtt_client.publish(topic, json.dumps(payload), qos=1)
    log.info(f"PC2_Output — ctrl: {payload}")


# ─── Actuadores — comandos ao mazerun ─────────────────────────────────────────
# Cada actuador:
# 1. Publica o comando no TopicAction (mazerun executa)
# 2. Actualiza o estado no MySQL (CorridorStatus)
# 3. Notifica o PC1_Input via publish_ctrl (para validação de movimentos)

def send_score(room):
    """Publica mensagem de Score para a sala — mazerun actualiza pontuação."""
    publish({"Type": "Score", "Player": player_number, "Room": room})

def ac_on():
    global ac_ligado
    if not ac_ligado:
        publish({"Type": "AcOn", "Player": player_number})
        ac_ligado = True
        log.info("PC2_Output - AC ligado")


def ac_off():
    global ac_ligado
    if ac_ligado:
        publish({"Type": "AcOff", "Player": player_number})
        ac_ligado = False
        log.info("PC2_Output - AC desligado")


def close_door(room_a, room_b):
    """Fecha corredor, actualiza MySQL e notifica PC1_Input."""
    publish({"Type": "CloseDoor", "Player": player_number,
             "RoomOrigin": room_a, "RoomDestiny": room_b})
    update_corridor_status(room_a, room_b, 0)
    publish_ctrl({"Type": "CorridorClosed", "RoomA": room_a, "RoomB": room_b})


def open_door(room_a, room_b):
    """Abre corredor, actualiza MySQL e notifica PC1_Input."""
    publish({"Type": "OpenDoor", "Player": player_number,
             "RoomOrigin": room_a, "RoomDestiny": room_b})
    update_corridor_status(room_a, room_b, 1)
    publish_ctrl({"Type": "CorridorOpened", "RoomA": room_a, "RoomB": room_b})


def close_all_doors():
    """
    Circuit breaker — fecha todos os corredores de uma vez.
    Mais eficiente que fechar um a um pois usa o comando CloseAllDoor do mazerun.
    Notifica o PC1_Input de cada corredor individualmente para manter o estado correcto.
    """
    publish({"Type": "CloseAllDoor", "Player": player_number})
    update_all_corridors(0)
    log.info("PC2_Output - todos os corredores fechados (circuit breaker)")
    for (room_a, room_b) in valid_corridors:
        publish_ctrl({"Type": "CorridorClosed", "RoomA": room_a, "RoomB": room_b})


def open_all_doors():
    """
    Reabre todos os corredores após o ruído baixar.
    Notifica o PC1_Input de cada corredor individualmente.
    """
    publish({"Type": "OpenAllDoor", "Player": player_number})
    update_all_corridors(1)
    log.info("PC2_Output - todos os corredores reabertos")
    for (room_a, room_b) in valid_corridors:
        publish_ctrl({"Type": "CorridorOpened", "RoomA": room_a, "RoomB": room_b})


# ─── Base de Dados — leituras e escrita ───────────────────────────────────────

def update_corridor_status(room_a, room_b, status):
    """Actualiza estado de um corredor específico no MySQL."""
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
        log.error(f"Erro ao actualizar corredor {room_a}→{room_b}: {e}")



def update_all_corridors(status):
    """Actualiza todos os corredores da simulação de uma vez."""
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
        log.error(f"Erro ao actualizar todos os corredores: {e}")


def fechar_corredores_sala(room):
    """
    Fecha todos os corredores que dão acesso a uma sala específica.
    Chamado quando uma sala atinge 3 gatilhos — fica inacessível.
    """
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
            log.info(f"PC2_Output - corredor {c['RoomA']}→{c['RoomB']} fechado (sala {room} esgotada)")
    except Exception as e:
        log.error(f"Erro ao fechar corredores sala {room}: {e}")



def get_pending_triggers():
    """
    Lê da tabela Mensagens os alertas ODD_EQUAL_EVEN ainda não processados.
    Considera 'não processado' um alerta que não tem entrada no TriggerLog
    com timestamp posterior ao alerta — e cuja sala ainda não esgotou (< 3 gatilhos).
    Esta query é executada a cada 0.5s — é o mecanismo de polling central do script.
    """
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
    """Conta quantos gatilhos já foram accionados para uma sala."""
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

def get_last_temperature():
    """Lê a última leitura de temperatura para esta simulação."""
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
    """Lê a última leitura de som para esta simulação."""
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
    """
    Identifica salas de baixa prioridade para fecho de corredor por ruído.
    Ordena por diferença entre marsамis odd e even (maior diferença = menor prioridade)
    e por número de gatilhos já accionados (mais gatilhos = menor prioridade).
    Exclui salas já esgotadas (3 gatilhos).
    """
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

# ─── Lógica de gatilhos ───────────────────────────────────────────────────────
# O trigger SQL em MedicoesPassagens detecta ODD=EVEN e insere em Mensagens.
# O PC2_Output lê Mensagens via polling e processa os gatilhos pendentes.
# O SP_AcionarGatilho verifica novamente a condição ODD=EVEN no momento da chamada:
#   - Se ainda ODD=EVEN → Score + 1.0 e regista no TriggerLog
#   - Se já não ODD=EVEN → Score - 0.5 (condição passou durante o delay de rede)

def CALL_SP(room):
    """
    Chama o SP_AcionarGatilho que verifica e regista o gatilho.
    O SP é a única forma de garantir que a verificação ODD=EVEN
    e o registo no TriggerLog são atómicos — sem race conditions.
    """
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
    """
    Sequência correcta de processamento de um gatilho:
    1. Verifica ocupação actual da sala
    2. Chama SP_AcionarGatilho — verifica ODD=EVEN e regista
    3. Só depois publica o Score no MQTT para o mazerun
    Esta ordem garante que o registo existe antes do MQTT ser publicado.
    """

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

          # Se ODD != EVEN no momento exacto — condição passou, não actua
          if occupancy["NumeroMarsamisOdd"] != occupancy["NumeroMarsamisEven"]:
              log.info(f"PC2_Output — sala {room}: ODD!=EVEN no momento da verificação, ignorado")
              return None

          # Publica Score primeiro — resposta mais rápida à cloud
          send_score(room)

          # Registo interno — secundário, para controlo de fecho de corredores
          CALL_SP(room)
          return "ok"

      except Exception as e:
          log.error(f"Erro ao acionar gatilho sala {room}: {e}")
          return None


def process_triggers():
    """
    Processa todos os gatilhos ODD_EQUAL_EVEN pendentes.
    Para cada gatilho:
    1. Chama SP e publica Score
    2. Verifica se a sala atingiu 3 gatilhos — se sim fecha os seus corredores
    """
    pending = get_pending_triggers()
    for trigger in pending:
        room = trigger["Sala"]
        log.info(f"PC2_Output — gatilho detectado sala {room}")
        result = send_score_and_log(room)
        if result:
            total = get_trigger_count(room)
            if total >= 3:
                log.info(f"PC2_Output — sala {room} esgotada ({total} gatilhos)")
                fechar_corredores_sala(room)



# ─── Gestão de actuadores ─────────────────────────────────────────────────────
# Corre a cada CHECK_INTERVAL_ACTUATORS segundos.
# Lê temperatura e som actuais e decide sobre AC e corredores.
# Os rácios são calculados relativamente ao valor máximo configurado
# para que os thresholds sejam independentes dos valores absolutos.

def manage_actuators():
    global ac_ligado, emergency_close_active

    temp  = get_last_temperature()
    sound = get_last_sound()

    if temp is None or sound is None:
        return

    # Calcular limites a partir da configuração da simulação
    temp_max  = float(simulation_config["NormalTemperature"]) + float(simulation_config["TempHighToleration"])
    temp_min  = float(simulation_config["NormalTemperature"]) - float(simulation_config["TempLowToleration"])
    noise_max = float(simulation_config["NormalNoise"]) + float(simulation_config["NoiseVarToleration"])

    # Rácios relativos ao máximo — independentes dos valores absolutos
    temp_ratio  = temp  / temp_max  if temp_max  > 0 else 0
    noise_ratio = sound / noise_max if noise_max > 0 else 0

    # ── Gestão de temperatura — AC ────────────────────────────────────────────
    if temp_ratio >= TEMP_AC_ON_THRESHOLD and not ac_ligado:
        log.info(f"Temperatura {temp:.1f} ({temp_ratio*100:.0f}%) > {TEMP_AC_ON_THRESHOLD*100:.0f}% — a ligar AC")
        ac_on()
    elif temp_ratio <= TEMP_AC_OFF_THRESHOLD and ac_ligado:
        log.info(f"Temperatura {temp:.1f} ({temp_ratio*100:.0f}%) < {TEMP_AC_OFF_THRESHOLD*100:.0f}% — a desligar AC")
        ac_off()

    # ── Gestão de ruído — corredores ──────────────────────────────────────────
    # Nível 3: > 90% — circuit breaker — fecha tudo e liga AC
    if noise_ratio >= NOISE_EMERGENCY_THRESHOLD and not emergency_close_active:
        log.warning(f"Ruído {sound:.1f} ({noise_ratio*100:.0f}%) > 90% — CIRCUIT BREAKER")
        close_all_doors()
        ac_on()
        emergency_close_active = True

    # Recuperação do circuit breaker: < 60% — reabre tudo e desliga AC
    elif noise_ratio <= NOISE_REOPEN_THRESHOLD and emergency_close_active:
        log.info(f"Ruído {sound:.1f} ({noise_ratio*100:.0f}%) < 60% — a reabrir corredores")
        open_all_doors()
        ac_off()
        emergency_close_active = False

    # Nível 2: > 70% mas < 90% — fecha corredor de sala com menor prioridade
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

    # Heartbeat — thread daemon, corre para sempre independentemente das simulações
    threading.Thread(target=heartbeat_thread, daemon=True, name="heartbeat").start()

    while True:
        # Reset do estado a cada nova simulação
        # Garante que o AC e o circuit breaker não ficam activos de simulações anteriores
        ac_ligado              = False
        emergency_close_active = False
        sim_ended_event.clear()  # reset do evento para nova simulação

        # Carrega configuração e corredores válidos do MySQL
        load_config()
        load_valid_corridors()

        # Cliente MQTT dedicado a este script — só publica, não subscreve
        # client_id fixo — identificável nos logs do broker
        # clean_session=True — não precisa de sessão persistente (só publica)
        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="pisid_grupo35_pc2_output",
            clean_session=True
        )
        mqtt_client.connect(
            simulation_config["Broker"],
            simulation_config["PortBroker"],
            keepalive=60
        )
        mqtt_client.loop_start()

        log.info(f"PC2_Output - a monitorizar simulação {simulation_id}...")

        # ── Threads da simulação ──────────────────────────────────────────────
        # Cada thread tem uma responsabilidade única e corre independentemente.
        # sim_ended_event coordena o fim sem polling individual ao MySQL.

        def simulation_monitor():
            """
            Verifica o estado da simulação no MySQL a cada 2s.
            Quando detecta Status != 1, activa sim_ended_event — notifica
            todas as outras threads simultaneamente sem polling individual.
            """
            while not sim_ended_event.is_set():
                try:
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
                        log.info(f"PC2_Output — simulação {simulation_id} terminou")
                        sim_ended_event.set()
                        return
                except Exception as e:
                    log.error(f"Erro no simulation_monitor: {e}")
                time.sleep(2)

        def trigger_processor():
            """
            Processa gatilhos ODD_EQUAL_EVEN a cada 0.5s.
            Independente do actuator_manager — um gatilho é processado
            imediatamente sem esperar pela verificação de temperatura/som.
            Após fim de simulação entra em modo flush — processa pendentes
            antes de terminar.
            """
            while not sim_ended_event.is_set():
                try:
                    process_triggers()
                except Exception as e:
                    log.error(f"Erro no trigger_processor: {e}")
                time.sleep(0.5)

            # Modo flush — processa gatilhos pendentes após fim de simulação
            log.info("PC2_Output — flush de gatilhos pendentes...")
            for attempt in range(10):
                pending = get_pending_triggers()
                if not pending:
                    log.info(f"PC2_Output — flush completo em {attempt+1} ciclos")
                    break
                process_triggers()
                time.sleep(1)
            else:
                log.warning("PC2_Output — timeout no flush de gatilhos")

        def actuator_manager():
            """
            Gere AC e corredores a cada CHECK_INTERVAL_ACTUATORS segundos.
            Independente do trigger_processor — a gestão de actuadores
            não bloqueia nem é bloqueada pelo processamento de gatilhos.
            """
            while not sim_ended_event.is_set():
                try:
                    manage_actuators()
                except Exception as e:
                    log.error(f"Erro no actuator_manager: {e}")
                time.sleep(CHECK_INTERVAL_ACTUATORS)

        # Arrancar as 3 threads da simulação
        threads = [
            threading.Thread(target=simulation_monitor, name="sim_monitor",   daemon=True),
            threading.Thread(target=trigger_processor,  name="trigger_proc",  daemon=True),
            threading.Thread(target=actuator_manager,   name="actuator_mgr",  daemon=True),
        ]
        for t in threads:
            t.start()

        # Aguarda que todas as threads terminem
        for t in threads:
            t.join()

        # Fim de simulação — desliga MQTT e aguarda nova simulação
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        log.info("PC2_Output - a aguardar nova simulação...")
        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
