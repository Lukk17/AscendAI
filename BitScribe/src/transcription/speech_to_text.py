import os
from datetime import datetime

os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import torch
import transformers
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
import soundfile as sf

WHISPER_SAMPLING_RATE = 16000


def print_configuration(model_folder, audio_path):
    print(f"[LLM] Config:\n"
          f"Model default sampling rate: {WHISPER_SAMPLING_RATE}\n"
          f"Model folder: {model_folder}\n"
          f"Audio path: {audio_path}\n"
          "Library versions:\n"
          f"transformers: {transformers.__version__}\n"
          f"torch: {torch.__version__}\n"
          f"soundfile: {sf.__version__}\n"
          "\n")


def initialize_model(model_folder):
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_folder, dtype=dtype, low_cpu_mem_usage=True, use_safetensors=True
    )
    model.to(device)

    processor = AutoProcessor.from_pretrained(model_folder)
    processor.tokenizer.pad_token_id = model.config.eos_token_id

    pipe = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        max_new_tokens=128,
        chunk_length_s=30,
        batch_size=16,
        dtype=dtype,
        device=device,
        ignore_warning=True,
    )
    return pipe


def check_audio(audio_path):
    _, original_sampling_rate = sf.read(audio_path)
    if original_sampling_rate != WHISPER_SAMPLING_RATE:
        print(f"WARN: original sampling rate ({original_sampling_rate}) not same as model's ({WHISPER_SAMPLING_RATE}).")


def process_audio(audio_path, pipe):
    return pipe(audio_path, return_timestamps=True, generate_kwargs={"language": "polish"})


def calculate_duration(start_time, stop_time):
    duration = stop_time - start_time
    duration_in_s = duration.total_seconds()

    hours = int(duration_in_s // 3600)
    minutes = int((duration_in_s % 3600) // 60)
    seconds = int(duration_in_s % 60)

    return f"Duration: {hours:02}:{minutes:02}:{seconds:02}"


def transcript_speach(model_folder, audio_path):
    start_time = datetime.now()
    print(f"[LLM] Start Time:{start_time.strftime('%Y-%m-%d %H:%M:%S')} \n")

    print_configuration(model_folder, audio_path)
    pipe = initialize_model(model_folder)
    check_audio(audio_path)

    result = process_audio(audio_path, pipe)

    stop_time = datetime.now()
    print(f"\n[LLM] Stop Time: {stop_time.strftime('%Y-%m-%d %H:%M:%S')}")

    return result['chunks'], calculate_duration(start_time, stop_time)
