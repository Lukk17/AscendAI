from concurrent.futures import ProcessPoolExecutor

import asyncio
import logging
import os
import tempfile
import torch
from faster_whisper import WhisperModel
from pydub import AudioSegment

logger = logging.getLogger(__name__)

CHUNK_LENGTH_MINUTES = 15
CHUNK_LENGTH_MS = CHUNK_LENGTH_MINUTES * 60 * 1000


def _transcribe_chunk(model_path: str, audio_chunk_path: str) -> list:
    """
    This function runs in a separate process.
    It loads the model, transcribes a single audio chunk, and returns the segments.
    This isolates the memory-intensive work from the main server process.
    """
    logger.info(f"[Worker] Loading model '{model_path}' for chunk '{audio_chunk_path}'...")
    try:
        if torch.cuda.is_available():
            device, compute_type = "cuda", "float16"
        else:
            device, compute_type = "cpu", "int8"

        model = WhisperModel(model_path, device=device, compute_type=compute_type)

        logger.info(f"[Worker] Transcribing chunk '{audio_chunk_path}'...")
        segments, _ = model.transcribe(audio_chunk_path, beam_size=5, language="pl")

        # The result from the generator needs to be converted to a list to be returned
        return list(segments)

    except Exception as e:
        logger.exception(f"[Worker] Error processing chunk '{audio_chunk_path}'.")
        # Re-raise the exception so the main process knows the task failed
        raise e


async def local_speech_transcription_stream(model_path: str, audio_path: str):
    """
    Splits a long audio file into chunks and transcribes them in separate processes
    to prevent memory-related crashes. Yields segments with corrected timestamps.
    """
    logger.info(f"Starting transcription for '{audio_path}' with chunking.")

    try:
        audio = AudioSegment.from_file(audio_path)
        logger.info(f"Audio loaded successfully. Duration: {len(audio) / 1000:.2f}s")
    except Exception as e:
        logger.exception("Pydub failed to load the audio file.")
        raise IOError("Failed to load audio file. It may be corrupt or an unsupported format.") from e

    # Create a ProcessPoolExecutor to run transcriptions in separate processes
    # max_workers=1 ensures only one chunk is processed at a time, conserving GPU memory.
    with ProcessPoolExecutor(max_workers=1) as executor:
        loop = asyncio.get_running_loop()
        tasks = []
        temp_files = []

        for i, start_ms in enumerate(range(0, len(audio), CHUNK_LENGTH_MS)):
            end_ms = start_ms + CHUNK_LENGTH_MS
            chunk = audio[start_ms:end_ms]

            # Export chunk to a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                chunk.export(tmp.name, format="wav")
                temp_files.append(tmp.name)
                logger.info(
                    f"Created audio chunk {i + 1} ({start_ms / 1000:.2f}s to {end_ms / 1000:.2f}s) at '{tmp.name}'")

                # Schedule the transcription task to run in the process pool
                task = loop.run_in_executor(
                    executor, _transcribe_chunk, model_path, tmp.name
                )
                tasks.append((task, start_ms / 1000))  # Store task and its time offset

        logger.info(f"Scheduled {len(tasks)} transcription tasks.")

        for i, (task, time_offset) in enumerate(tasks):
            try:
                logger.info(f"Waiting for chunk {i + 1}/{len(tasks)} to complete...")
                segments = await task
                logger.info(f"Chunk {i + 1} completed. Processing {len(segments)} segments.")

                # Yield segments with corrected timestamps
                for segment in segments:
                    corrected_start = segment.start + time_offset
                    corrected_end = segment.end + time_offset

                    # Create a new object to yield to avoid modifying the original
                    yield type('Segment', (), {
                        'text': segment.text,
                        'start': corrected_start,
                        'end': corrected_end
                    })()

            except Exception as e:
                logger.exception(f"A worker process for chunk {i + 1} failed.")
                # We can choose to stop or continue. For now, we stop.
                raise RuntimeError(f"Transcription failed on chunk {i + 1}. See logs for details.") from e
            finally:
                # Clean up the temporary file for this chunk
                if temp_files[i]:
                    try:
                        os.remove(temp_files[i])
                        logger.info(f"Cleaned up temp file: {temp_files[i]}")
                    except OSError:
                        pass

    logger.info("Finished processing all chunks.")
