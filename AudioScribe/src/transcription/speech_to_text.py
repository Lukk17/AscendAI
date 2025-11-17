import asyncio
import logging
import multiprocessing as mp
import os
import tempfile
import torch
from faster_whisper import WhisperModel
from pydub import AudioSegment

from src.config.settings import settings

logger = logging.getLogger(__name__)

CHUNK_LENGTH_MS = settings.CHUNK_LENGTH_MINUTES * 60 * 1000


def _transcribe_and_communicate(
        model_path: str,
        audio_path: str,
        result_queue: mp.Queue,
        shutdown_event: mp.Event
):
    """
    This is the target function for the worker process.
    """
    setup_logging()
    process_id = os.getpid()
    logger.info(f"[Worker {process_id}] Process started.")

    temp_audio_chunk_files = []
    try:
        logger.info(f"[Worker {process_id}] Loading model '{model_path}'...")
        if torch.cuda.is_available():
            device, compute_type = "cuda", "float16"
        else:
            device, compute_type = "cpu", "int8"
        model = WhisperModel(model_path, device=device, compute_type=compute_type)
        logger.info(f"[Worker {process_id}] Model loaded successfully.")

        audio = AudioSegment.from_file(audio_path)
        logger.info(f"[Worker {process_id}] Audio loaded. Duration: {len(audio) / 1000:.2f}s.")

        num_chunks = (len(audio) // CHUNK_LENGTH_MS) + 1
        logger.info(f"[Worker {process_id}] Slicing audio into {num_chunks} chunks.")

        all_segments = []
        for i, start_ms in enumerate(range(0, len(audio), CHUNK_LENGTH_MS)):
            chunk_num = i + 1
            logger.info(f"[Worker {process_id}] Processing chunk {chunk_num}/{num_chunks}...")
            end_ms = start_ms + CHUNK_LENGTH_MS
            chunk = audio[start_ms:end_ms]

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
                chunk.export(tmp_audio.name, format="wav")
                temp_audio_chunk_files.append(tmp_audio.name)

                segments_chunk, _ = model.transcribe(
                    tmp_audio.name,
                    beam_size=settings.BEAM_SIZE,
                    language=settings.TRANSCRIPTION_LANGUAGE,
                    best_of=settings.BEST_OF,
                    condition_on_previous_text=settings.CONDITION_ON_PREVIOUS_TEXT,
                    vad_filter=settings.VAD_FILTER,
                    vad_parameters=settings.VAD_PARAMETERS,
                    temperature=settings.TEMPERATURE
                )

                time_offset = start_ms / 1000
                for segment in segments_chunk:
                    all_segments.append({
                        "text": segment.text.strip(),
                        "start": segment.start + time_offset,
                        "end": segment.end + time_offset
                    })
            logger.info(f"[Worker {process_id}] Chunk {chunk_num}/{num_chunks} complete.")

        logger.info(
            f"[Worker {process_id}] All chunks processed. Sending {len(all_segments)} segments back to main process.")
        result_queue.put(all_segments)

    except Exception as e:
        logger.exception(f"[Worker {process_id}] An error occurred.")
        result_queue.put(e)
    finally:
        logger.info(f"[Worker {process_id}] Waiting for shutdown signal from main process.")
        shutdown_event.wait()

        for f_path in temp_audio_chunk_files:
            try:
                os.remove(f_path)
            except OSError:
                pass
        logger.info(f"[Worker {process_id}] Shutdown signal received. Exiting.")


async def local_speech_transcription_stream(model_path: str, audio_path: str):
    """
    Launches and manages a worker process to safely transcribe a long audio file.
    """
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

    ctx = mp.get_context('spawn')
    result_queue = ctx.Queue()
    shutdown_event = ctx.Event()

    logger.info(f"[Master process] Spawning worker for transcription of '{audio_path}'.")
    worker_process = ctx.Process(
        target=_transcribe_and_communicate,
        args=(model_path, audio_path, result_queue, shutdown_event)
    )
    worker_process.start()

    logger.info("[Master process] Waiting for results from worker process...")
    result = await asyncio.to_thread(result_queue.get)
    logger.info("[Master process] Results received from worker.")

    logger.info("[Master process] Sending shutdown signal to worker.")
    shutdown_event.set()

    if isinstance(result, Exception):
        logger.error("[Master process] Worker process failed with an exception.")
        raise result

    logger.info(f"[Master process] Yielding {len(result)} segments.")
    for segment_dict in result:
        yield type('Segment', (), {
            'text': segment_dict['text'],
            'start': segment_dict['start'],
            'end': segment_dict['end']
        })()

    await asyncio.to_thread(worker_process.join, timeout=10)
    if worker_process.is_alive():
        logger.warning("[Master process] Worker process did not terminate cleanly. Forcing termination.")
        worker_process.terminate()

    logger.info("[Master process] Transcription stream finished.")


# This import is needed for the worker process to find the logging setup function
from src.config.logging_config import setup_logging
