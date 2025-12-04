import os
import re
from typing import List
import logging
from openai import OpenAI

openai_client = OpenAI()

MEMORY_CATEGORIZATION_PROMPT = """You are a memory categorization assistant. 
Given a memory, categorize it into 1-3 relevant categories. 
Return ONLY a comma-separated list of categories. Example: personal, work, hobbies
"""

def get_categories_for_memory(memory: str) -> List[str]:
    try:
        messages = [
            {"role": "system", "content": MEMORY_CATEGORIZATION_PROMPT},
            {"role": "user", "content": memory}
        ]

        # Get model from environment variable, fallback to known working model
        model_name = os.getenv("LLM_MODEL", "meta-llama-3.1-8b-instruct")

        # Use standard create call, compatible with all OpenAI clients
        completion = openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0
        )

        content = completion.choices[0].message.content
        # Simple regex to split by comma and clean up
        categories = [cat.strip().lower() for cat in re.split(r",", content) if cat.strip()]
        return categories

    except Exception as e:
        logging.error(f"[ERROR] Failed to get categories: {e}")
        return ["uncategorized"]
