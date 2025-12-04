#!/bin/bash
set -e

echo
echo
echo "🧩 Configuring OpenMemory (Bulk Update)..."

echo
echo "🧩 Configuring OpenMemory (Bulk Update)..."

config_payload=$(cat <<EOF
{
  "mem0": {
    "vector_store": {
      "provider": "qdrant",
      "config": {
        "host": "${QDRANT_HOST:-qdrant}",
        "port": ${QDRANT_PORT:-6333},
        "collection_name": "${QDRANT_COLLECTION:-openmemory}",
        "embedding_model_dims": ${EMBEDDING_DIMS:-768}
      }
    },
    "embedder": {
      "provider": "openai",
      "config": {
        "model": "${EMBEDDER_MODEL:-nomic-ai/nomic-embed-text-v1.5-GGUF}"
      }
    },
    "llm": {
      "provider": "openai",
      "config": {
        "model": "${LLM_MODEL:-meta-llama-3.1-8b-instruct}",
        "temperature": 0.1,
        "max_tokens": ${LLM_MAX_TOKENS:-1500}
      }
    }
  }
}
EOF
)

curl -fsS -X PUT "http://openmemory:8765/api/v1/config/" \
  -H 'Content-Type: application/json' \
  -d "$config_payload"

echo
echo "🗑️  Resetting Qdrant collection to ensure correct dimensions..."
# Sleep to ensure config is applied and reloaded
sleep 2
curl -v -X DELETE "http://${QDRANT_HOST:-qdrant}:${QDRANT_PORT:-6333}/collections/${QDRANT_COLLECTION:-openmemory}"
echo "✅ Collection reset request sent."

echo
echo "🆕 Recreating collection with ${EMBEDDING_DIMS:-768} dimensions..."

qdrant_payload=$(cat <<EOF
{
  "vectors": {
    "size": ${EMBEDDING_DIMS:-768},
    "distance": "${QDRANT_DISTANCE:-Cosine}"
  }
}
EOF
)

curl -fsS -X PUT "http://${QDRANT_HOST:-qdrant}:${QDRANT_PORT:-6333}/collections/${QDRANT_COLLECTION:-openmemory}" \
  -H 'Content-Type: application/json' \
  -d "$qdrant_payload"
echo "✅ Collection recreated with ${EMBEDDING_DIMS:-768} dimensions."

echo
echo "✅ Configuration complete!"

