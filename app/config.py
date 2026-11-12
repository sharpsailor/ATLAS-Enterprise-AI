from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # S3 (LocalStack by default; leave aws_endpoint_url empty for real AWS)
    aws_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_default_region: str = "us-east-1"
    s3_bucket: str = "atlas-docs"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_chunks: int = 0  # per document; 0 = unlimited. Hosted: protects the free LLM quota

    # Ollama stands in for Bedrock (Titan embeddings + Nova Lite)
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "llama3.2"
    embed_model: str = "mxbai-embed-large"
    embed_dim: int = 1024

    # Hosted: setting GEMINI_API_KEY switches chat + embeddings from Ollama to Gemini
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_backup_model: str = "gemini-3.1-flash-lite"  # asked too when the first is slow; "" = off
    hedge_after_seconds: float = 6.0
    gemini_embed_model: str = "gemini-embedding-001"

    pinecone_api_key: str = ""
    pinecone_index_host: str = ""

    database_url: str = "postgresql://atlas:atlas@localhost:5440/atlas"

    app_password: str = ""  # set when hosted: admin password for uploads and approval decisions
    chat_limit_per_hour: int = 0  # per visitor IP; 0 = unlimited

    min_relevance: float = 0.45
    hitl_enabled: bool = True
    memory_turns: int = 6

    rius_api_key: str = ""
    rius_service_name: str = "atlas-ai-enterprise"
    rius_disabled: bool = False
    rius_capture_content: bool = False


settings = Settings()
