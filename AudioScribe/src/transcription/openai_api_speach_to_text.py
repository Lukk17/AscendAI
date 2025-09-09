import os
import openai

openai.api_key = os.environ.get("OPENAI_API_KEY")


def openai_transcript(audio_file_path):
    if not openai.api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set!")

    with open(audio_file_path, "rb") as audio_file:
        return openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="pl"
        )
