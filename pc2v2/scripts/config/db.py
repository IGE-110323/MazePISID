import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv
from pymongo import MongoClient
from dbutils.pooled_db import PooledDB

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# ─── MongoDB ──────────────────────────────────────────────────────────────────

def get_mongo_client():
    uri = os.getenv("MONGO_URI")
    client = MongoClient(uri)
    return client

def get_mongo_db():
    client = get_mongo_client()
    db_name = os.getenv("MONGO_DB")
    return client[db_name]

# ─── MySQL Pool ───────────────────────────────────────────────────────────────

_mysql_pool = None

def _get_mysql_pool():
    global _mysql_pool
    if _mysql_pool is None:
        _mysql_pool = PooledDB(
            creator        = pymysql,
            maxconnections = 10,
            mincached      = 2,
            maxcached      = 5,
            blocking       = True,
            host           = os.getenv("MYSQL_HOST",     "127.0.0.1"),
            port           = int(os.getenv("MYSQL_PORT", "3306")),
            user           = os.getenv("MYSQL_USER",     "root"),
            password       = os.getenv("MYSQL_PASSWORD", "pisid1234"),
            database       = os.getenv("MYSQL_DB",       "pisid"),
            charset        = "utf8mb4",
            cursorclass    = pymysql.cursors.DictCursor,
            autocommit     = True,
            ping           = 1,
        )
    return _mysql_pool

def get_mysql_connection():
    """
    Devolve uma conexão da pool MySQL.
    conn.close() devolve a conexão à pool em vez de a fechar fisicamente.
    """
    return _get_mysql_pool().connection()

# ─── Configuração da simulação ────────────────────────────────────────────────

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
