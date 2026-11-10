"""Self-healing per-domain CSS selector recipes.

Key ``recipe:{registrable_domain}:{sha256 of canonical schema}`` in Redis,
TTL ``RECIPE_TTL_SECONDS``. A replay runs the stored selectors with
``lxml.cssselect``, builds the object and validates it with ``jsonschema``. A
replay that fails validation, or that leaves a required field empty, deletes
the recipe so the caller runs the model again. Selectors are plain CSS
strings, never JavaScript and never XPath, and a selector longer than
``RECIPE_SELECTOR_MAX_CHARS`` is never stored. A recipe is stored only when
its selectors, replayed on the page they came from, give exactly the values the
model returned. A recipe with a selector that
names the whole document (its first match is ``html``, ``head`` or ``body``,
or holds the whole text of the page) is never stored and never replayed,
because any page would replay it into an object that still validates.
"""

import json
import logging
from typing import Any

import jsonschema
import redis.asyncio as redis
from cssselect import SelectorError
from lxml import html as lxml_html

from src.config.config import settings
from src.reader.schema_extraction import sanitize_selectors

logger = logging.getLogger(__name__)

_DOCUMENT_TAGS = frozenset({"html", "head", "body"})


def recipe_key(domain: str, digest: str) -> str:
    """Redis key shape for one domain and schema."""
    return f"recipe:{domain}:{digest}"


class _RecipeClientHolder:
    client: redis.Redis | None = None


def recipe_redis() -> redis.Redis | None:
    """Shared recipe client, or None when no Redis URL is configured."""
    if _RecipeClientHolder.client is not None:
        return _RecipeClientHolder.client
    if not settings.REDIS_URL:
        return None
    _RecipeClientHolder.client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    return _RecipeClientHolder.client


async def lookup(domain: str, digest: str) -> dict[str, str] | None:
    """Stored selectors for one domain and schema, or None on a miss or bad record."""
    client = recipe_redis()
    if client is None:
        return None
    try:
        raw = await client.get(recipe_key(domain, digest))
    except Exception:
        logger.warning("recipe_store: lookup failed for %s", domain)

        return None
    if raw is None:
        return None
    try:
        record: Any = json.loads(raw)
        selectors = sanitize_selectors(record.get("selectors"))
    except (ValueError, AttributeError):
        logger.warning("recipe_store: corrupt record for %s", domain)

        return None
    if not selectors:
        return None

    return selectors


def _normalised_text(element: Any) -> str:
    return " ".join(element.text_content().split())


def names_whole_document(page_html: str, selectors: dict[str, str]) -> bool:
    """True when a selector's first match on *page_html* is the document rather than one field.

    The selectors already passed `sanitize_selectors`. A page that cannot be
    parsed counts as matched, so nothing unverified is stored.
    """
    try:
        tree = lxml_html.document_fromstring(page_html)
    except Exception:
        return True
    bodies = tree.xpath("//body")
    whole_text = _normalised_text(bodies[0] if bodies else tree)
    for selector in selectors.values():
        matches = tree.cssselect(selector)
        if not matches:
            continue
        first = matches[0]
        if first.tag in _DOCUMENT_TAGS or (whole_text and _normalised_text(first) == whole_text):
            return True

    return False


async def store(
    domain: str,
    digest: str,
    selectors: dict[str, str],
    page_html: str,
    *,
    expected: dict[str, Any],
    schema: dict[str, Any],
) -> bool:
    """Store selectors that pass `sanitize_selectors` and replay *expected* on *page_html*, with the TTL."""
    kept = sanitize_selectors(selectors)
    if not kept:
        return False
    if names_whole_document(page_html, kept):
        logger.warning("recipe_store: refusing a document-wide recipe for %s", domain)

        return False
    if build_object(page_html, kept, schema) != expected:
        logger.info("recipe_store: refusing a recipe that does not replay the model values for %s", domain)

        return False
    client = recipe_redis()
    if client is None:
        return False
    try:
        await client.set(
            recipe_key(domain, digest),
            json.dumps({"selectors": kept}),
            ex=settings.RECIPE_TTL_SECONDS,
        )
    except Exception:
        logger.warning("recipe_store: store failed for %s", domain)

        return False

    return True


async def delete(domain: str, digest: str) -> None:
    """Drop one recipe, so the next read runs the model again."""
    client = recipe_redis()
    if client is None:
        return
    try:
        await client.delete(recipe_key(domain, digest))
    except Exception:
        logger.warning("recipe_store: delete failed for %s", domain)


def apply_selectors(page_html: str, selectors: dict[str, str]) -> dict[str, Any]:
    """Run stored selectors against page HTML, never raising."""
    try:
        tree = lxml_html.fromstring(page_html)
    except Exception:
        return {}
    found: dict[str, Any] = {}
    for field, selector in selectors.items():
        try:
            matches = tree.cssselect(selector)
        except SelectorError:
            continue
        if matches:
            found[field] = matches[0].text_content().strip()

    return found


def replay_valid(obj: dict[str, Any], schema: dict[str, Any]) -> bool:
    """True when a replayed object validates and keeps every required field."""
    try:
        jsonschema.validate(obj, schema)
    except (jsonschema.ValidationError, jsonschema.SchemaError):
        return False
    required = schema.get("required", [])
    for field in required:
        value = obj.get(field)
        if value is None or value == "":
            return False

    return True


def coerce_field(value: Any, field_schema: dict[str, Any]) -> Any:
    """Coerce replayed selector text to the schema's scalar type."""
    if not isinstance(value, str):
        return value
    declared = field_schema.get("type")
    if isinstance(declared, str):
        wanted = [declared]
    elif isinstance(declared, list):
        wanted = [entry for entry in declared if isinstance(entry, str)]
    else:
        return value
    text = value.strip()
    try:
        if "integer" in wanted and "number" not in wanted:
            return int(text)
        if "number" in wanted:
            return float(text)
        if "boolean" in wanted:
            if text.lower() in ("true", "1", "yes"):
                return True
            if text.lower() in ("false", "0", "no"):
                return False
    except ValueError:
        return value

    return value


def build_object(page_html: str, selectors: dict[str, str], schema: dict[str, Any]) -> dict[str, Any]:
    """Run stored selectors and coerce each value to its schema type."""
    raw = apply_selectors(page_html, selectors)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return raw
    built: dict[str, Any] = {}
    for field, value in raw.items():
        subschema = properties.get(field)
        if isinstance(subschema, dict):
            built[field] = coerce_field(value, subschema)
        else:
            built[field] = value

    return built


__all__ = [
    "apply_selectors",
    "build_object",
    "coerce_field",
    "delete",
    "lookup",
    "names_whole_document",
    "recipe_key",
    "recipe_redis",
    "replay_valid",
    "store",
]
