from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # MariaDB
    DB_HOST: str
    DB_PORT: int = 3306
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_SCHEMA: str = ""

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Config paths
    SCHEMA_MAP_PATH: str = "/app/config/schema_map.yaml"
    NEWS_SOURCES_PATH: str = "/app/config/news_sources.txt"

    # LLM
    LLM_PROVIDER: str = "none"  # none | ollama
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b-instruct"

    # Redis/Qdrant
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    QDRANT_URL: str = "http://qdrant:6333"
    
    # Vector DB & Embedding
    QDRANT_COLLECTION_NEWS: str = "news_items"
    EMBED_PROVIDER: str = "ollama"  # ollama | none

    class Config:
        env_file = ".env"


settings = Settings()
