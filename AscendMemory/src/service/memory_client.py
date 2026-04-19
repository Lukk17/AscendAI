import logging
from typing import List, Optional, Dict, Any

from mem0 import Memory
from mem0.llms.openai import OpenAILLM

from src.config.config import settings, PROVIDER_CONFIGS

logger = logging.getLogger(__name__)

_original_generate_response = OpenAILLM.generate_response


def _generate_response_stripping_unsupported_json_object_format(self, messages, response_format=None, tools=None,
                                                                tool_choice="auto"):
    if response_format == {"type": "json_object"}:
        logger.warning(f"Stripping unsupported response_format: {response_format}")
        response_format = None
    return _original_generate_response(self, messages, response_format, tools, tool_choice)


OpenAILLM.generate_response = _generate_response_stripping_unsupported_json_object_format

# Per-provider singleton instances keyed by provider name
_client_instances: Dict[str, 'AscendMemoryClient'] = {}


def resolve_provider(provider: Optional[str]) -> str:
    """Resolve provider name, falling back to configured default."""
    if provider and provider.strip():
        return provider.strip().lower()
    return settings.MEM0_DEFAULT_PROVIDER


def get_memory_client(provider: Optional[str] = None) -> 'AscendMemoryClient':
    """
    Returns the AscendMemoryClient for the given provider.
    Lazy-initializes per-provider singleton instances.
    """
    resolved = resolve_provider(provider)
    if resolved not in _client_instances:
        logger.info(f"Initializing AscendMemoryClient for provider '{resolved}'...")
        _client_instances[resolved] = AscendMemoryClient(resolved)
    return _client_instances[resolved]


def get_default_memory_client() -> 'AscendMemoryClient':
    """FastAPI Depends-compatible factory for the default provider (used for warmup and DI)."""
    return get_memory_client()


class AscendMemoryClient:
    def __init__(self, provider: str):
        provider_config = PROVIDER_CONFIGS.get(provider)
        if provider_config is None:
            logger.warning(
                f"Unknown provider '{provider}', falling back to default '{settings.MEM0_DEFAULT_PROVIDER}'")
            provider_config = PROVIDER_CONFIGS[settings.MEM0_DEFAULT_PROVIDER]

        collection_name = provider_config["collection_name"]
        embedding_model = provider_config["embedding_model"]
        embedding_dims = provider_config["embedding_dims"]

        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "host": settings.QDRANT_HOST,
                    "port": settings.QDRANT_PORT,
                    "collection_name": collection_name,
                    "embedding_model_dims": embedding_dims
                }
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": settings.MEM0_LLM_MODEL,
                    "api_key": settings.OPENAI_API_KEY,
                    "openai_base_url": settings.OPENAI_BASE_URL
                }
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": embedding_model,
                    "api_key": settings.OPENAI_API_KEY,
                    "openai_base_url": settings.OPENAI_BASE_URL
                }
            }
        }
        self.memory = Memory.from_config(config)
        self.provider = provider
        logger.info(
            f"[AscendMemory] Initialized client | provider={provider} | collection={collection_name} | "
            f"embedder={embedding_model} | dims={embedding_dims}")

    def search(self, query: str, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for memories. Returns a list of dicts with 'memory', 'score', etc."""
        try:
            results = self.memory.search(query=query, user_id=user_id, limit=limit)
            return results.get("results", []) if results else []
        except Exception as e:
            logger.error(f"Error searching memory for user {user_id} (provider={self.provider}): {e}")
            return []

    def add(self, user_id: str, messages: Optional[List[Dict[str, str]]] = None, text: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Add memory. Accepts either messages (list of {role, content}) or raw text.
        Returns the result from mem0, which includes the memory ID.
        """
        try:
            result = {}
            if messages:
                result = self.memory.add(messages=messages, user_id=user_id, metadata=metadata,
                                         infer=settings.MEM0_INFER_MEMORY)
            elif text:
                result = self.memory.add(messages=[{"role": "user", "content": text}], user_id=user_id,
                                         metadata=metadata, infer=settings.MEM0_INFER_MEMORY)
            else:
                raise ValueError("Either 'messages' or 'text' must be provided.")

            return result.get("results", [])
        except Exception as e:
            logger.error(f"Error adding memory for user {user_id} (provider={self.provider}): {e}")
            raise

    def delete(self, memory_id: str) -> None:
        """Delete a single memory by ID."""
        try:
            self.memory.delete(memory_id=memory_id)
        except Exception as e:
            logger.error(f"Error deleting memory {memory_id} (provider={self.provider}): {e}")
            raise

    def wipe_user(self, user_id: str) -> None:
        """
        Delete all memories for a user.
        Uses individual deletes as a workaround for mem0 bug where delete_all resets the entire collection.
        """
        try:
            all_memories = self.memory.get_all(user_id=user_id)
            memories_list = all_memories.get("results", [])

            logger.info(f"Wiping {len(memories_list)} memories for user {user_id} (provider={self.provider})")

            for mem in memories_list:
                try:
                    self.memory.delete(memory_id=mem["id"])
                except Exception as del_e:
                    logger.error(f"Failed to delete memory {mem['id']}: {del_e}")

        except Exception as e:
            logger.error(f"Error wiping memory for user {user_id} (provider={self.provider}): {e}")
            raise