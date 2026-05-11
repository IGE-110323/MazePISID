import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# ─── MongoDB Singleton ────────────────────────────────────────────────────────
_mongo_client = None

def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(
            os.getenv("MONGO_URI"),
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
    return _mongo_client

def get_mongo_db():
    return get_mongo_client()[os.getenv("MONGO_DB")]

# ─── MySQL ────────────────────────────────────────────────────────────────────
# Usado apenas pelo PC1_Agent para leitura de configuração — não usa pool
# porque são chamadas pontuais no arranque, não em loop contínuo

def get_mysql_connection():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "pisid1234"),
        database=os.getenv("MYSQL_DB", "pisid"),
        charset="utf8mb4",
        connect_timeout=10,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor
    )

def get_simulation_config(simulation_id):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            sc.Broker, sc.PortBroker,
            sc.TopicMovement, sc.TopicSound, sc.TopicTemperature, sc.TopicAction,
            sc.TimeMarsamiLive, sc.ParamAcLimit,
            sc.ErrorOutlierSound, sc.ErrorOutlierTemp,
            m.NormalNoise, m.NoiseVarToleration,
            m.NormalTemperature, m.TempHighToleration, m.TempLowToleration,
            s.PlayerNumber
        FROM Simulacao s
        JOIN SimulationConfig sc ON sc.IDConfig = s.IDConfig
        JOIN Maze m ON m.IDMaze = sc.IDMaze
        WHERE s.IDSimulacao = %s
    """, (simulation_id,))
    config = cursor.fetchone()
    cursor.close()
    conn.close()
    return config