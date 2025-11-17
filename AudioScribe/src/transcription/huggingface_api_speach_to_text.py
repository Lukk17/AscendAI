import os
import logging
from huggingface_hub import InferenceClient
from huggingface_hub.inference._generated.types import AutomaticSpeechRecognitionOutput
from huggingface_hub.utils import HfHubHTTPError

from src.config.settings import settings

logger = logging.getLogger(__name__)

def hf_transcript(audio_file_path: str, model: str):
    """
    Transcribes an audio file using a Hugging Face Inference Endpoint.
    """
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise ValueError("HF_TOKEN environment variable not set!")

    client = InferenceClient(provider="auto", token=hf_token)

    try:
        # Note: The HF Inference API doesn't have a standardized 'language' parameter
        # for the ASR task. It's often part of the model's configuration itself.
        # We pass it here in case the model supports it as a generate_kwargs.
        result: AutomaticSpeechRecognitionOutput = client.automatic_speech_recognition(
            audio_file_path,
            model=model,
            generate_kwargs={"language": settings.TRANSCRIPTION_LANGUAGE}
        )
        return result.get("text")
    except HfHubHTTPError as e:
        logger.error(f"Hugging Face API error for model '{model}': {e}")
        # This can happen if the model is invalid or the provider has issues
        raise ValueError(f"Could not access model '{model}' via Hugging Face API. It may be invalid or unavailable.") from e
    except Exception as e:
        logger.error(f"Error processing audio file '{audio_file_path}' with Hugging Face API: {e}")
        raise IOError(f"Failed to process audio file with HF API. It may be corrupt or in an unsupported format.") from e
