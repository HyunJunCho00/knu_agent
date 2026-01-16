import redis
from qdrant_client import QdrantClient
from neo4j import GraphDatabase
from app.core.config import settings

class DBManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DBManager, cls).__new__(cls)
            
            # 1. Redis 연결
            cls._instance.redis = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=0,
                decode_responses=True
            )
            
            # [cite_start]2. Qdrant 연결 (knu_notice_retriever.py [cite: 50-52] 참고)
            cls._instance.qdrant = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
                verify=False
            )
            
            # [cite_start]3. Neo4j 연결 (knu_graph_builder.py [cite: 8] 참고)
            cls._instance.neo4j_driver = GraphDatabase.driver(
                settings.NEO4J_URI, 
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )
        return cls._instance

    def close(self):
        self.neo4j_driver.close()
        self.redis.close()

db = DBManager()