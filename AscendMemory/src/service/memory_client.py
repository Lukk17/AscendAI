import hashlib
import logging
import threading
from typing import Any

from mem0 import Memory

from src.config.config import (
    PROVIDER_CONFIGS,
    provider_settings_value,
    settings,
    supported_providers,
)

logger = logging.getLogger(__name__)

# Per-provider singleton instances keyed by provider name. The lock guards
# the check-then-set; without it two concurrent first-hit requests for the
# same provider both instantiate AscendMemoryClient (which opens Qdrant +
# LLM clients — heavy and wasteful).
_client_instances: dict[str, "AscendMemoryClient"] = {}
_client_lock = threading.Lock()


def resolve_provider(provider: str | None) -> str:
    """Resolve a caller-supplied provider name to one of the recognised
    PROVIDER_CONFIGS keys. PROVIDER_CONFIGS is the source of truth.

    None or whitespace falls back to settings.MEM0_DEFAULT_PROVIDER.
    An unknown string raises ValueError listing the allowed set — we never
    silently substitute the default, because doing so would route a caller's
    data to the wrong collection without their consent.
    """

    if provider is None or not provider.strip():
        return settings.MEM0_DEFAULT_PROVIDER

    candidate = provider.strip().lower()
    if candidate not in PROVIDER_CONFIGS:
        raise ValueError(
            f"Unknown provider '{candidate}'. Allowed: {supported_providers()}"
        )
    return candidate


def get_memory_client(provider: str | None = None) -> "AscendMemoryClient":
    """Returns the AscendMemoryClient for the given provider. Lazy-initialises
    a per-provider singleton under a thread lock so concurrent first-hit
    requests don't construct duplicate heavy clients."""

    resolved = resolve_provider(provider)
    existing = _client_instances.get(resolved)
    if existing is not None:
        return existing

    with _client_lock:
        # Re-check inside the lock: another thread may have populated the
        # cache while we were waiting.
        existing = _client_instances.get(resolved)
        if existing is not None:
            return existing

        logger.info(f"Initializing AscendMemoryClient for provider '{resolved}'...")
        instance = AscendMemoryClient(resolved)
        _client_instances[resolved] = instance

        return instance


def get_default_memory_client() -> "AscendMemoryClient":
    """FastAPI Depends-compatible factory for the default provider."""

    return get_memory_client()


def _hash_user_id(user_id: str) -> str:
    """Stable short hash for log lines. user_id is frequently PII (email,
    account UUID); we want correlation across log lines without writing the
    raw value to disk / Loki."""

    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]


class AscendMemoryClient:
    def __init__(self, provider: str) -> None:
        # Provider is assumed validated by resolve_provider before reaching
        # here — no silent fallback at this layer.
        provider_cfg = PROVIDER_CONFIGS[provider]

        collection_name = provider_cfg["collection_name"]
        embedding_model = provider_cfg["embedding_model"]
        embedding_dims = provider_cfg["embedding_dims"]
        llm_provider = provider_cfg["llm_provider"]

        base_url = provider_settings_value(provider_cfg["base_url_setting"])
        api_key = provider_settings_value(provider_cfg["api_key_setting"])

        if not api_key or not api_key.strip():
            raise ValueError(
                f"Provider '{provider}' requires env var {provider_cfg['api_key_setting']} "
                "but it is missing or blank. Set it before invoking this provider."
            )

        # mem0 2.x ships a native `lmstudio` LLM provider that knows the
        # response_format quirks LM Studio rejects, so the old monkey-patch
        # of OpenAILLM.generate_response is gone. For lmstudio the LLM block
        # uses provider="lmstudio" with a `lmstudio_base_url` field; for
        # OpenAI / Gemini the LLM block uses provider="openai".
        llm_config: dict[str, Any] = {
            "model": settings.MEM0_LLM_MODEL,
            "api_key": api_key,
        }
        if llm_provider == "lmstudio":
            llm_config["lmstudio_base_url"] = base_url
        else:
            llm_config["openai_base_url"] = base_url

        config: dict[str, Any] = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "host": settings.QDRANT_HOST,
                    "port": settings.QDRANT_PORT,
                    "collection_name": collection_name,
                    "embedding_model_dims": embedding_dims,
                },
            },
            "llm": {
                "provider": llm_provider,
                "config": llm_config,
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": embedding_model,
                    "api_key": api_key,
                    "openai_base_url": base_url,
                    "embedding_dims": embedding_dims,
                },
            },
        }
        self.memory = Memory.from_config(config)
        self.provider = provider
        logger.info(
            f"[AscendMemory] Initialized client | provider={provider} | "
            f"collection={collection_name} | embedder={embedding_model} | "
            f"dims={embedding_dims} | base_url={base_url} | llm_provider={llm_provider}"
        )

    def search(self, query: str, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search memories. Returns a list of {memory, score, ...} dicts.

        Surfaces upstream exceptions (Qdrant down, embedder timeout) instead
        of silently returning []; callers map them to /problem+json 5xx so
        outages are observable end-to-end. mem0 2.x search uses
        `top_k` (was `limit`) and `filters={"user_id": ...}` (was a direct
        `user_id` kwarg).
        """

        try:
            result = self.memory.search(
                query=query,
                top_k=limit,
                filters={"user_id": user_id},
            )
            if not result:
                return []

            # mem0 2.x search/add both return a dict with a "results" list.
            results: list[dict[str, Any]] = result.get("results", [])
            return results
        except Exception:
            logger.exception(
                f"Error searching memory user_hash={_hash_user_id(user_id)} provider={self.provider}"
            )
            raise

    def add(
        self,
        user_id: str,
        messages: list[dict[str, str]] | None = None,
        text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Add memory. Accepts either chat-shaped messages (`[{role, content}]`)
        or raw text. mem0 wraps raw text as a single user message."""

        try:
            if messages:
                result = self.memory.add(
                    messages=messages,
                    user_id=user_id,
                    metadata=metadata,
                    infer=settings.MEM0_INFER_MEMORY,
                )
            elif text:
                result = self.memory.add(
                    messages=[{"role": "user", "content": text}],
                    user_id=user_id,
                    metadata=metadata,
                    infer=settings.MEM0_INFER_MEMORY,
                )
            else:
                raise ValueError("Either 'messages' or 'text' must be provided.")

            # mem0 2.x search/add both return a dict with a "results" list.
            results: list[dict[str, Any]] = result.get("results", [])
            return results
        except Exception:
            logger.exception(
                f"Error adding memory user_hash={_hash_user_id(user_id)} provider={self.provider}"
            )
            raise

    def delete(self, memory_id: str) -> None:
        """Delete a single memory by ID."""

        try:
            self.memory.delete(memory_id=memory_id)
        except Exception:
            logger.exception(f"Error deleting memory_id={memory_id} provider={self.provider}")
            raise

    def wipe_user(self, user_id: str) -> None:
        """Delete every memory for a user.

        mem0 1.x `delete_all` called `vector_store.reset()` after the per-id
        delete loop, which wiped every other user's memories sharing the
        same collection. mem0 2.0.4 removed that reset call, so the safe
        path is now a single `delete_all` invocation — no manual loop, no
        custom Qdrant filter delete.
        """

        try:
            self.memory.delete_all(user_id=user_id)
            logger.info(
                f"Wiped memories for user_hash={_hash_user_id(user_id)} provider={self.provider}"
            )
        except Exception:
            logger.exception(
                f"Error wiping memory user_hash={_hash_user_id(user_id)} provider={self.provider}"
            )
            raise
