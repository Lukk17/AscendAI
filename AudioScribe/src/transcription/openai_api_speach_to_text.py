import logging
from openai import OpenAI, APIError

logger = logging.getLogger(__name__)

# The OpenAI client automatically reads the OPENAI_API_KEY from the environment.
client = OpenAI()


def openai_transcript(audio_file_path: str, model: str = "whisper-1"):
    """
    Transcribes an audio file using the OpenAI Whisper API.
    """
    try:
        with open(audio_file_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                language="pl"
            )
        return response.text
    except APIError as e:
        logger.error(f"OpenAI API error for model '{model}': {e}")
        # This can happen if the model name is invalid or the API is down
        raise ValueError(
            f"Could not access model '{model}' via OpenAI API. It may be invalid or the API may be unavailable.") from e
    except Exception as e:
        logger.error(f"Error processing audio file '{audio_file_path}' with OpenAI API: {e}")
        raise IOError(
            f"Failed to process audio file with OpenAI API. It may be corrupt or in an unsupported format.") from e
