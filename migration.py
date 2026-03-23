import mysql.connector
from pymongo import MongoClient
import paho.mqtt.client as mqtt
import time
from datetime import datetime

# ---- Configuração MongoDB ----
mongo_client = MongoClient("mongodb://localhost:27017/")
db = mongo_client["pisid"]
col_movements = db["movement_readings"]
col_sound     = db["sound_readings"]
col_temp      = db["temp_readings"]

# ---- Configuração MySQL ----
mysql = mysql.connector.connect(
    host="localhost",
    port=3307,
    user="root",
    password="admin",
    database="pisid"
)
cursor = mysql.cursor()

# ---- Configuração MQTT ----
BROKER = "broker.hivemq.com"
PORT   = 1883
TOPIC  = "pisid_mazeact"
PLAYER = 35

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"MQTT ligado: {reason_code}")

def on_publish(client, userdata, mid, reason_code, properties):
    print(f"MQTT mensagem publicada: mid={mid}")

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_publish = on_publish
mqtt_client.connect(BROKER, PORT)
mqtt_client.loop_start()
time.sleep(1)

ID_SIMULATION    = None
last_movement_id = None
last_sound_id    = None
last_temp_id     = None
SESSION_START    = datetime.now()

# -------------------------------------------------------
# SETUP INICIAL
# -------------------------------------------------------

def setup():
    global ID_SIMULATION

    # Marcar simulação anterior como finished
    cursor.execute("""
        UPDATE Simulation SET status = 'finished', dateTimeEnd = %s
        WHERE status = 'active'
    """, (datetime.now(),))
    mysql.commit()

    # Criar nova simulação
    cursor.execute("""
        INSERT INTO Simulation (team, description, dateTimeStart, status)
        VALUES (35, 'Simulação automática', %s, 'active')
    """, (datetime.now(),))
    mysql.commit()
    ID_SIMULATION = cursor.lastrowid
    print(f"Nova simulação criada com ID: {ID_SIMULATION}")

# -------------------------------------------------------
# FUNÇÕES AUXILIARES
# -------------------------------------------------------

def insert_room_if_not_exists(room_id):
    if room_id is None or room_id == 0:
        return
    cursor.execute("SELECT ID FROM Room WHERE ID = %s", (room_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO Room (ID, name) VALUES (%s, %s)",
            (room_id, f"Room {room_id}")
        )
        mysql.commit()

    cursor.execute("""
        SELECT ID_room FROM RoomSimulation
        WHERE ID_simulation = %s AND ID_room = %s
    """, (ID_SIMULATION, room_id))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO RoomSimulation (ID_simulation, ID_room, oddCount, evenCount)
            VALUES (%s, %s, 0, 0)
        """, (ID_SIMULATION, room_id))
        mysql.commit()
        print(f"Nova sala: Room {room_id}")

def insert_corridor_if_not_exists(room_origin, room_destiny):
    if room_origin == 0 or room_destiny == 0:
        return
    cursor.execute("""
        SELECT ID FROM Corridor WHERE roomOrigin = %s AND roomDestiny = %s
    """, (room_origin, room_destiny))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO Corridor (roomOrigin, roomDestiny, active)
            VALUES (%s, %s, 1)
        """, (room_origin, room_destiny))
        mysql.commit()
        print(f"Novo corredor: {room_origin} → {room_destiny}")

def insert_marsami_if_not_exists(marsami_id):
    cursor.execute("SELECT type FROM Marsami WHERE ID = %s", (marsami_id,))
    result = cursor.fetchone()
    if not result:
        marsami_type = 'even' if marsami_id % 2 == 0 else 'odd'
        cursor.execute(
            "INSERT INTO Marsami (ID, type) VALUES (%s, %s)",
            (marsami_id, marsami_type)
        )
        mysql.commit()
        print(f"Novo marsami: {marsami_id} ({marsami_type})")
        return marsami_type
    return result[0]

def update_room_simulation(room_origin, room_destiny, marsami_type, status):
    if status == 2 and room_origin == 0 and room_destiny == 0:
        return

    field = "oddCount" if marsami_type == 'odd' else "evenCount"

    if room_origin != 0:
        cursor.execute(f"""
            UPDATE RoomSimulation
            SET {field} = GREATEST(0, {field} - 1)
            WHERE ID_simulation = %s AND ID_room = %s
        """, (ID_SIMULATION, room_origin))

    if room_destiny != 0:
        cursor.execute(f"""
            UPDATE RoomSimulation
            SET {field} = {field} + 1
            WHERE ID_simulation = %s AND ID_room = %s
        """, (ID_SIMULATION, room_destiny))

    mysql.commit()

def check_trigger(room_id):
    if room_id is None or room_id == 0:
        return
    cursor.execute("""
        SELECT oddCount, evenCount FROM RoomSimulation
        WHERE ID_simulation = %s AND ID_room = %s
    """, (ID_SIMULATION, room_id))
    result = cursor.fetchone()
    if not result:
        return
    odd, even = result
    if odd == even and odd > 0:
        cursor.execute("""
            SELECT COUNT(*) FROM Messages
            WHERE ID_simulation = %s AND room = %s AND alertType = 'trigger'
        """, (ID_SIMULATION, room_id))
        count = cursor.fetchone()[0]

        if count >= 3:
            return

        cursor.execute("""
            SELECT ID FROM Messages
            WHERE ID_simulation = %s AND room = %s
              AND alertType = 'trigger' AND message = %s
        """, (ID_SIMULATION, room_id, f"odd={odd},even={even}"))
        if not cursor.fetchone():
            payload = "{Type: Score, Player:" + str(PLAYER) + ", Room: " + str(room_id) + "}"
            pub_result = mqtt_client.publish(TOPIC, payload, qos=1)
            pub_result.wait_for_publish()
            cursor.execute("""
                INSERT INTO Messages (room, sensor, alertType, message, writtenAt, ID_simulation)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                room_id, 'trigger', 'trigger',
                f"odd={odd},even={even}",
                datetime.now(), ID_SIMULATION
            ))
            mysql.commit()
            print(f"🎯 GATILHO! Sala {room_id} | odd={odd} even={even} | Disparo {count+1}/3 | Publicado: {payload}")

# -------------------------------------------------------
# MIGRAÇÃO
# -------------------------------------------------------

def migrate_movements():
    global last_movement_id

    query = {"receivedAt": {"$gte": SESSION_START}}
    if last_movement_id:
        query["_id"] = {"$gt": last_movement_id}

    for doc in col_movements.find(query).sort("_id", 1):
        try:
            room_origin  = doc.get("RoomOrigin", 0)
            room_destiny = doc.get("RoomDestiny", 0)
            marsami_id   = doc.get("Marsami")
            status       = doc.get("Status")

            if marsami_id is None:
                last_movement_id = doc["_id"]
                continue

            insert_room_if_not_exists(room_origin)
            insert_room_if_not_exists(room_destiny)
            insert_corridor_if_not_exists(room_origin, room_destiny)
            marsami_type = insert_marsami_if_not_exists(marsami_id)

            cursor.execute("""
                INSERT INTO MovementReadings
                (ID_simulation, time, writtenAt, roomOrigin, roomDestiny, marsami, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                ID_SIMULATION,
                doc.get("receivedAt", datetime.now()),
                datetime.now(),
                room_origin if room_origin != 0 else None,
                room_destiny if room_destiny != 0 else None,
                marsami_id,
                status
            ))
            mysql.commit()

            update_room_simulation(room_origin, room_destiny, marsami_type, status)
            check_trigger(room_destiny)

            last_movement_id = doc["_id"]
            print(f"Movimento | Marsami {marsami_id} | {room_origin} → {room_destiny} | Status {status}")

        except Exception as e:
            print(f"Erro ao migrar movimento: {e}")
            mysql.rollback()

def migrate_temperature():
    global last_temp_id

    query = {"receivedAt": {"$gte": SESSION_START}}
    if last_temp_id:
        query["_id"] = {"$gt": last_temp_id}

    for doc in col_temp.find(query).sort("_id", 1):
        try:
            value    = doc.get("Temperature")
            time_val = doc.get("Hour") or doc.get("receivedAt") or datetime.now()

            cursor.execute("""
                INSERT INTO Temperature (ID_simulation, value, time)
                VALUES (%s, %s, %s)
            """, (ID_SIMULATION, value, time_val))
            mysql.commit()

            last_temp_id = doc["_id"]
            print(f"Temperatura: {value}")

        except Exception as e:
            print(f"Erro ao migrar temperatura: {e}")
            mysql.rollback()

def migrate_sound():
    global last_sound_id

    query = {"receivedAt": {"$gte": SESSION_START}}
    if last_sound_id:
        query["_id"] = {"$gt": last_sound_id}

    for doc in col_sound.find(query).sort("_id", 1):
        try:
            value    = doc.get("Sound")
            time_val = doc.get("Hour") or doc.get("receivedAt") or datetime.now()

            cursor.execute("""
                INSERT INTO Sound (ID_simulation, value, time)
                VALUES (%s, %s, %s)
            """, (ID_SIMULATION, value, time_val))
            mysql.commit()

            last_sound_id = doc["_id"]
            print(f"Som: {value}")

        except Exception as e:
            print(f"Erro ao migrar som: {e}")
            mysql.rollback()

# -------------------------------------------------------
# LOOP PRINCIPAL
# -------------------------------------------------------

print("A iniciar migração MongoDB → MySQL...")
setup()

while True:
    migrate_movements()
    migrate_temperature()
    migrate_sound()
    time.sleep(1)