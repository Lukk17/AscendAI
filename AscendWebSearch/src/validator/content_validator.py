import logging

import textstat

from src.config.config import settings

logger = logging.getLogger(__name__)


class ContentValidator:
    def validate(self, text: str) -> bool:
        if self._is_empty(text):
            logger.warning("Validation Failed: Empty or None text.")
            return False

        if self._contains_error_keywords(text):
            logger.warning("Validation Failed: Error keyword found.")
            return False

        if not self._is_sufficient_length(text):
            logger.warning("Validation Failed: text too short.")
            return False

        return self._passes_quality_metrics(text)

    def _is_empty(self, text: str) -> bool:
        return not text or not text.strip()

    def _contains_error_keywords(self, text: str) -> bool:
        return any(keyword in text for keyword in settings.ERROR_KEYWORDS)

    def _is_sufficient_length(self, text: str) -> bool:
        return len(text.split()) >= settings.VALIDATION_MIN_WORDS

    def _passes_quality_metrics(self, text: str) -> bool:
        try:
            words = text.split()
            lexicon_count = textstat.lexicon_count(text, removepunct=True)
            flesch_score = textstat.flesch_reading_ease(text)

            if lexicon_count < settings.VALIDATION_MIN_WORDS and flesch_score < settings.MIN_FLESCH_SCORE:
                logger.warning(
                    f"Validation Failed: Low quality content (Lexicon: {lexicon_count} < {settings.VALIDATION_MIN_WORDS}, Flesch: {flesch_score}).")
                return False

            if self._is_repetitive(words):
                return False

        except Exception as e:
            logger.warning(f"Textstat validation error: {e}. Proceeding with content.")

        return True

    def _is_repetitive(self, words: list) -> bool:
        word_count = len(words)
        if word_count > 50:
            unique_words = len(set(words))
            ttr = unique_words / word_count
            if ttr < settings.MIN_TTR:
                logger.warning(f"Validation Failed: Low TTR ({ttr:.2f}). Content is consistent repetition.")
                return True
        return False
