#!/bin/bash
set -e

echo "⏳ Waiting for OpenMemory API to be ready at http://openmemory:8765..."
i=0
while [ $i -lt 60 ]; do
  # Try health endpoint first, then config endpoint
  if curl -s -f http://openmemory:8765/openapi.json > /dev/null 2>&1; then
    echo "✅ OpenMemory API is ready!"
    break
  fi
  sleep 2
  i=$((i+1))
done

if [ $i -ge 60 ]; then
  echo "❌ Timed out waiting for OpenMemory API to be ready."
  exit 1
fi

echo
echo "🧩 Configuring OpenMemory (Bulk Update)..."
curl -fsS -X PUT "http://openmemory:8765/api/v1/config/" \
  -H 'Content-Type: application/json' \
  -d '{
  "mem0": {
    "vector_store": {
      "provider": "qdrant",
      "config": {
        "host": "qdrant",
        "port": 6333,
        "collection_name": "openmemory",
        "embedding_model_dims": 768
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
        "max_tokens": 1500
      }
    }
  }
  }'

echo
echo "🗑️  Resetting Qdrant collection to ensure correct dimensions..."
# Sleep to ensure config is applied and reloaded
sleep 2
curl -v -X DELETE "http://qdrant:6333/collections/openmemory"
echo "✅ Collection reset request sent."

echo
echo "🆕 Recreating collection with 768 dimensions..."
curl -fsS -X PUT "http://qdrant:6333/collections/openmemory" \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {
      "size": 768,
      "distance": "Cosine"
    }
  }'
echo "✅ Collection recreated with 768 dimensions."

echo
echo "✅ Configuration complete!"

