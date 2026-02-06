import logging
from typing import List, Optional, Dict, Any

from mem0 import Memory
from mem0.llms.openai import OpenAILLM

from src.config.config import settings

logger = logging.getLogger(__name__)

_original_generate_response = OpenAILLM.generate_response


def _generate_response_stripping_unsupported_json_object_format(self, messages, response_format=None, tools=None,
                                                                tool_choice="auto"):
    if response_format == {"type": "json_object"}:
        logger.warning(f"Stripping unsupported response_format: {response_format}")
        response_format = None
    return _original_generate_response(self, messages, response_format, tools, tool_choice)


OpenAILLM.generate_response = _generate_response_stripping_unsupported_json_object_format

# Singleton instance
_client_instance: Optional['AscendMemoryClient'] = None


def get_memory_client() -> 'AscendMemoryClient':
    """
    Returns the singleton instance of AscendMemoryClient.
    Lazy initializes if not already created.
    """
    global _client_instance
    if _client_instance is None:
        logger.info("Initializing Singleton AscendMemoryClient...")
        _client_instance = AscendMemoryClient()
    return _client_instance


class AscendMemoryClient:
    def __init__(self):
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "host": settings.QDRANT_HOST,
                    "port": settings.QDRANT_PORT,
                    "collection_name": settings.MEM0_COLLECTION_NAME,
                    "embedding_model_dims": settings.MEM0_EMBEDDING_DIMS
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
                    "model": settings.MEM0_EMBEDDING_MODEL,
                    "api_key": settings.OPENAI_API_KEY,
                    "openai_base_url": settings.OPENAI_BASE_URL
                }
            }
        }
        self.memory = Memory.from_config(config)
        logger.info(
            f"Initialized Mem0 Memory Client with config: Qdrant Host={settings.QDRANT_HOST}, Embedder={settings.MEM0_EMBEDDING_MODEL}")

    def search(self, query: str, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search for memories.
        Returns a list of dicts. Each dict has 'memory', 'score', etc.
        """
        try:
            results = self.memory.search(query=query, user_id=user_id, limit=limit)
            return results.get("results", []) if results else []
        except Exception as e:
            logger.error(f"Error searching memory for user {user_id}: {e}")
            return []

    def add(self, user_id: str, messages: Optional[List[Dict[str, str]]] = None, text: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Add memory. 
        Accepts either messages (list of {role, content}) or raw text.
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
            logger.error(f"Error adding memory for user {user_id}: {e}")
            raise

    def delete(self, memory_id: str) -> None:
        """
        Delete a single memory by ID.
        """
        try:
            self.memory.delete(memory_id=memory_id)
        except Exception as e:
            logger.error(f"Error deleting memory {memory_id}: {e}")
            raise

    def wipe_user(self, user_id: str) -> None:
        """
        Delete all memories for a user.
        """
        try:
            # MEM0 BUG WORKAROUND:
            # Do NOT use self.memory.delete_all(user_id=user_id) because it resets the ENTIRE collection.
            # Instead, list all memories for the user and delete them one by one.
            all_memories = self.memory.get_all(user_id=user_id)
            memories_list = all_memories.get("results", [])

            logger.info(f"Wiping {len(memories_list)} memories for user {user_id}")

            for mem in memories_list:
                try:
                    self.memory.delete(memory_id=mem["id"])
                except Exception as del_e:
                    logger.error(f"Failed to delete memory {mem['id']}: {del_e}")

        except Exception as e:
            logger.error(f"Error wiping memory for user {user_id}: {e}")
            raise
