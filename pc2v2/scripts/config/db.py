import os

import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

def get_mongo_client():
    uri = os.getenv("MONGO_URI")
    client = MongoClient(uri)
    return client

def get_mongo_db():
    client = get_mongo_client()
    db_name = os.getenv("MONGO_DB")
    return client[db_name]

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
        cursorclass=pymysql.cursors.DictCursor  # equivalente a dictionary=True
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
