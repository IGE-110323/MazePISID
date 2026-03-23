import paho.mqtt.client as mqtt
from pymongo import MongoClient, ASCENDING
import json
from datetime import datetime
import hashlib

# ---- Configuração ----
BROKER = "broker.hivemq.com"
PORT = 1883
PLAYER = 35
TOPIC_MOV   = f"pisid_mazemov_{PLAYER}"
TOPIC_SOUND = f"pisid_mazesound_{PLAYER}"
TOPIC_TEMP  = f"pisid_mazetemp_{PLAYER}"

# ---- Limites válidos ----
MAX_ROOMS    = 10
MAX_MARSAMIS = 30
MAX_TEMP     = 40
MIN_TEMP     = 0.0
MAX_SOUND    = 40
MIN_SOUND    = 0.0
VALID_STATUS = [0, 1, 2]

# ---- Cache de deduplicação ----
recent_hashes = set()
MAX_CACHE = 200

def is_duplicate(payload_str):
    h = hashlib.md5(payload_str.encode()).hexdigest()
    if h in recent_hashes:
        return True
    recent_hashes.add(h)
    if len(recent_hashes) > MAX_CACHE:
        recent_hashes.clear()
    return False

# ---- Ligar ao MongoDB ----
mongo_client = MongoClient("mongodb://localhost:27017/")
db            = mongo_client["pisid"]
col_movements = db["movement_readings"]
col_sound     = db["sound_readings"]
col_temp      = db["temp_readings"]
col_dirty     = db["dirty_data"]

# ---- Índices simples para performance (sem unique) ----
col_movements.create_index([("Player", ASCENDING), ("receivedAt", ASCENDING)])
col_sound.create_index([("Player", ASCENDING), ("receivedAt", ASCENDING)])
col_temp.create_index([("Player", ASCENDING), ("receivedAt", ASCENDING)])

# -------------------------------------------------------
# FUNÇÕES DE VALIDAÇÃO
# -------------------------------------------------------

def save_dirty(data, topic, reason):
    col_dirty.insert_one({
        "originalData": data,
        "topic":        topic,
        "reason":       reason,
        "receivedAt":   datetime.now()
    })
    print(f"⚠️  Dado sujo | Motivo: {reason} | Dados: {data}")

def validate_hour(data, topic):
    hour_str = data.get("Hour")
    if hour_str is None:
        return True
    try:
        datetime.strptime(str(hour_str), "%Y-%m-%d %H:%M:%S.%f")
        return True
    except ValueError:
        save_dirty(data, topic, f"Invalid Hour format: {hour_str}")
        return False

def validate_movement(data, topic):
    room_origin  = data.get("RoomOrigin")
    room_destiny = data.get("RoomDestiny")
    marsami      = data.get("Marsami")
    status       = data.get("Status")

    if None in [room_origin, room_destiny, marsami, status]:
        save_dirty(data, topic, "Missing fields")
        return False

    if room_origin < 0:
        save_dirty(data, topic, f"Negative RoomOrigin: {room_origin}")
        return False

    if room_destiny < 0:
        save_dirty(data, topic, f"Negative RoomDestiny: {room_destiny}")
        return False

    if room_origin > MAX_ROOMS:
        save_dirty(data, topic, f"RoomOrigin out of range: {room_origin}")
        return False

    if room_destiny > MAX_ROOMS:
        save_dirty(data, topic, f"RoomDestiny out of range: {room_destiny}")
        return False

    if marsami <= 0:
        save_dirty(data, topic, f"Invalid Marsami ID: {marsami}")
        return False

    if marsami > MAX_MARSAMIS:
        save_dirty(data, topic, f"Marsami out of range: {marsami}")
        return False

    if status not in VALID_STATUS:
        save_dirty(data, topic, f"Invalid Status: {status}")
        return False

    return True

def validate_temperature(data, topic):
    temp = data.get("Temperature")

    if temp is None:
        save_dirty(data, topic, "Missing Temperature field")
        return False

    if temp < MIN_TEMP or temp > MAX_TEMP:
        save_dirty(data, topic, f"Temperature out of range: {temp}")
        return False

    return True

def validate_sound(data, topic):
    sound = data.get("Sound")

    if sound is None:
        save_dirty(data, topic, "Missing Sound field")
        return False

    if sound < MIN_SOUND or sound > MAX_SOUND:
        save_dirty(data, topic, f"Sound out of range: {sound}")
        return False

    return True

# -------------------------------------------------------
# MQTT
# -------------------------------------------------------

already_subscribed = False

def on_connect(client, userdata, flags, reason_code, properties):
    global already_subscribed
    if reason_code == 0:
        print(f"✅ Ligado ao broker {BROKER}!")
        if not already_subscribed:
            client.subscribe(TOPIC_MOV)
            client.subscribe(TOPIC_SOUND)
            client.subscribe(TOPIC_TEMP)
            already_subscribed = True
            print(f"À escuta nos tópicos do Player {PLAYER}...")
            print(f"  → {TOPIC_MOV}")
            print(f"  → {TOPIC_SOUND}")
            print(f"  → {TOPIC_TEMP}")
    else:
        print(f"Erro ao ligar. Código: {reason_code}")

def on_message(client, userdata, message):
    topic   = message.topic
    payload = message.payload.decode("utf-8")

    # ---- Descartar duplicados ----
    if is_duplicate(payload):
        print(f"🔁 Duplicado ignorado: {payload[:60]}...")
        return

    try:
        data = json.loads(payload)

        # ---- Filtrar mensagens de outros jogadores ----
        if data.get("Player") != PLAYER:
            return

        data["receivedAt"] = datetime.now()

        if topic == TOPIC_MOV:
            if validate_movement(data, topic):
                col_movements.insert_one(data)
                print(f"✅ MOVIMENTO: Marsami {data.get('Marsami')} | Sala {data.get('RoomOrigin')} → {data.get('RoomDestiny')} | Status {data.get('Status')}")

        elif topic == TOPIC_SOUND:
            if validate_hour(data, topic) and validate_sound(data, topic):
                col_sound.insert_one(data)
                print(f"✅ RUÍDO: {data.get('Sound')} | Hour: {data.get('Hour')}")

        elif topic == TOPIC_TEMP:
            if validate_hour(data, topic) and validate_temperature(data, topic):
                col_temp.insert_one(data)
                print(f"✅ TEMPERATURA: {data.get('Temperature')} | Hour: {data.get('Hour')}")

    except json.JSONDecodeError:
        save_dirty({"raw": payload}, topic, "Invalid JSON")
    except Exception as e:
        print(f"Erro inesperado: {e}")

# ---- Iniciar com clean_session=True ----
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=True)
client.on_connect = on_connect
client.on_message = on_message

print(f"A ligar ao broker {BROKER}...")
client.connect(BROKER, PORT, 60)
client.loop_forever()