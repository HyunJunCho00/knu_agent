import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    UPSTAGE_API_KEY: str
    QDRANT_URL: str
    QDRANT_API_KEY: str | None = None
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    REDIS_HOST: str
    REDIS_PORT: int

    class Config:
        env_file = ".env"

settings = Settings()