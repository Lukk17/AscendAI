
# AudioScribe

---

## Prerequisites

### Python
Version 3.11

Create [Virtual environment](#Virtual-environment)

### ffmpeg
Install for audio loading, chunking/resampling.

Linux:
```shell
sudo apt install ffmpeg
```

Windows admin terminal
```PowerShell
choco install ffmpeg
```
or https://ffmpeg.org/download.html


### Installing python dependencies

Using `requirements.txt` file  
PyTorch (CUDA 12.1)
```shell
pip install --index-url https://download.pytorch.org/whl/cu121 "torch==2.5.1+cu121"
```
```shell
pip install -r requirements.txt
```

Manually
```shell
# PyTorch (CUDA 12.1)
pip install --index-url https://download.pytorch.org/whl/cu121 "torch==2.5.1+cu121"
```
```shell
pip install "transformers==4.56.1" "tokenizers==0.22.0" "soundfile==0.13.1" "scipy==1.16.1" "openai==1.107.0" "numpy<2.0.0"
```
```shell
pip install "fastapi==0.116.1" "uvicorn==0.35.0"
```

```shell
pip install python-multipart
```

---
## Run
Run with port selection:

### Local
```shell
uvicorn main:app --host 0.0.0.0 --port 7017 --reload
```

### Docker

#### Build docker image
```shell
docker build -t audio-scribe:latest .
```

#### Run docker image

Make sure the directory `D:/Development/AI/models/LLM/safetensor/whisper-large-v3-speach-to-text` 
exists and is shared with Docker Desktop (Settings > Resources > File Sharing).


##### Using a local Whisper model

Linux:
```shell
docker run -d \
  --name audio-scribe \
  --gpus all \
  -p 7017:7017 \
  -e OPENAI_API_KEY="sk-..." \
  -e WHISPER_MODEL_PATH=/models/whisper \
  -v /absolute/path/to/whisper-large-v3:/models/whisper \
  bit-scribe:latest
```

Windows PowerShell
```PowerShell
docker run -d `
  --name audio-scribe `
  --gpus all `
  -p 7017:7017 `
  -e OPENAI_API_KEY="sk" `
  -e WHISPER_MODEL_PATH=/models/whisper `
  -v "D:/Development/AI/models/LLM/safetensor/whisper-large-v3-speach-to-text:/models/whisper" `
  bit-scribe:latest
```
- `--gpus all` tells Docker to allocate all available GPUs to the container.
- `-e WHISPER_MODEL_PATH` tells your app where the local Whisper model is located.
- `-v` is a bind mount: it does not copy. It makes the host folder visible at `/models/whisper` inside the container.  
    Your app should then load the model from that path.
- `-e OPENAI_API_KEY="sk-..."` sets `OPENAI_API_KEY` as environment variable.


##### Using HF cache
If you pass a model repo id (e.g., openai/whisper-large-v3) to from_pretrained, Transformers will download to the HF cache.

Linux:
```shell
docker run -d \
  --name audio-scribe \
  --gpus all \
  -p 7017:7017 \
  -e OPENAI_API_KEY="sk-..." \
  -e WHISPER_MODEL_PATH="openai/whisper-large-v3" \
  -e HF_HOME=/hf-cache \
  -v /host/hf-cache:/hf-cache \
  bit-scribe:latest
```

Windows powershell:
```PowerShell
docker run -d `
  --name audio-scribe `
  --gpus all `
  -p 7017:7017 `
  -e OPENAI_API_KEY="sk-..." `
  -e WHISPER_MODEL_PATH="openai/whisper-large-v3" `
  -e HF_HOME=/hf-cache `
  -v "D:/Development/AI/hf-cache:/hf-cache" `
  bit-scribe:latest
```
`-e HF_HOME=/hf-cache -v /host/hf-cache:/hf-cache` sets the cache dir to `/hf-cache` in the container  
    and maps it on your machine




---
## Creating requirements

To create requirements with a current python local installation type:
```shell
pip freeze > requirements.txt
```

---
## Virtual environment

### Using Intellij 

Settings > Project > Project Interpreter > Add > Create Virtual Environment

### Using python shell

Create venv in the project root directory: 
```powershell
C:\Python311\python.exe -m venv venv
```

Activate venv:
Windows:
```powershell
.\venv\Scripts\activate.ps1
```
Linux:
```shell
.\venv\Scripts\activate
```

---

## Troubleshooting

### CUDA version
If not working with CUDA 12.1, try to install CUDA 11.8:
```shell
# PyTorch (CUDA 11.8)
pip install --index-url https://download.pytorch.org/whl/cu118 "torch==2.5.1+cu118"
```

### Additional libs

`torchaudio` should not be needed, but anyway to install it:

```shell
pip install --index-url https://download.pytorch.org/whl/cu121 "torchaudio==2.5.1+cu121"

```
