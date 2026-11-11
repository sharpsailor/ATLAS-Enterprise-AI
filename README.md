# ATLAS-Enterprise-AI

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker
- [Ollama](https://ollama.com) installed locally, with the models pulled:
  `ollama pull llama3.2 && ollama pull mxbai-embed-large`
- A free LocalStack account (for the auth token)

## Setup

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt

cp .env.example .env    # then fill LOCALSTACK_AUTH_TOKEN, PINECONE_API_KEY, PINECONE_INDEX_HOST
docker compose up -d    # starts LocalStack (4566) and Postgres (5440)
python test/test.py     # checks the LLM + embeddings work
```

## Local services

| Service | Runs as | Address |
|---|---|---|
| S3, SQS, DynamoDB, Secrets Manager, EC2 | LocalStack (Docker) | `http://localhost:4566` |
| LLM + embeddings | Ollama (host) | `http://localhost:11434` |
| PostgreSQL 17 | Docker | `localhost:5440` (user/pass/db: `atlas`) |
| Vector index | Pinecone (cloud) | `PINECONE_INDEX_HOST` in `.env` |

- `infra/localstack-init.sh` runs on every LocalStack start and creates the
  `atlas-docs` bucket and `atlas-ingest` queue. The free plan has no
  persistence, so anything else you create is lost on restart.
- Browse resources at https://app.localstack.cloud → Resource Browser.
- To hit real AWS instead, unset `AWS_ENDPOINT_URL` and use real credentials.
- ECR and Bedrock are not on the LocalStack free plan; Ollama stands in for Bedrock.

Check what is running:

```bash
curl -s localhost:4566/_localstack/health
curl -s localhost:11434/api/tags
```
