
# AudioScribe

---
### OpenApi documentation

Swagger
http://localhost:7017/docs

Redoc
http://localhost:7017/redoc

---

## Temporary files

Removed after each request.

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

[Active correct(!) venv](#activate-venv)

Using `requirements.txt` file  

```shell
python.exe -m pip install --upgrade pip
```
PyTorch (CUDA 12.1)
```shell
pip install --index-url https://download.pytorch.org/whl/cu121 "torch==2.5.1+cu121"
```
```shell
pip install -r requirements.txt
```

Manually
```shell
python.exe -m pip install --upgrade pip
```
```shell
# PyTorch (CUDA 12.1)
pip install --index-url https://download.pytorch.org/whl/cu121 "torch==2.5.1+cu121"
```
```shell
pip install "transformers==4.56.1" "tokenizers==0.22.0" "soundfile==0.13.1" "scipy==1.16.1" "openai==1.107.0" "numpy<2.0.0" 
```
```shell
pip install "fastapi==0.116.1" "uvicorn==0.35.0" "aiofiles==24.1.0" "colorlog==6.9.0"
```

```shell
pip install python-multipart
```

---
## Run
Run with port selection:

### Local
User run configuration in `.run` directory named `AudioScribe`

Or run from the terminal with env variables:
```
WHISPER_MODEL_PATH=D:\Development\AI\models\LLM\safetensor\whisper-large-v3-speach-to-text;
OPENAI_API_KEY=sk
```
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
  audio-scribe:latest
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
  audio-scribe:latest
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
  audio-scribe:latest
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
  audio-scribe:latest
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
C:\Python311\python.exe -m venv .venv
```

#### Activate venv
Windows:
```powershell
.\AudioScribe\.venv\Scripts\activate.ps1
```
Linux:
```shell
.\AudioScribe\.venv\Scripts\activate
```

---

## Run as an MCP server (Model Context Protocol)

AudioScribe can also run as an MCP server so AI agents and compatible editors (e.g., Claude Desktop) can call its tools directly.

Prerequisites:
- Ensure ffmpeg and model dependencies are installed as in the regular setup.
- Install the MCP Python SDK dependency (already listed in requirements.txt as `mcp`).

Local run:
```shell
python mcp_server.py
```
This starts an MCP server over stdio. MCP-aware clients will spawn it and communicate via stdio.

Environment variables respected:
- OPENAI_API_KEY: required for the transcribe_openai tool.
- WHISPER_MODEL_PATH: path or HF model id for the local model used by transcribe_local.

Exposed MCP tools:
- health() -> "ok"
- transcribe_local(file_path: str) -> JSON string with keys: source, duration, transcription (segment list)
- transcribe_openai(file_path: str) -> JSON string with keys: source, transcription



#### Docker (MCP mode)

Use the same image but override the command to run the MCP server instead of FastAPI.

Build docker image
```shell
docker build -f Dockerfile.mcp -t audio-scribe:latest .
```

Linux:
```shell
docker run -it --rm \
  --name audio-scribe-mcp \
  --gpus all \
  -e OPENAI_API_KEY="sk-..." \
  -e WHISPER_MODEL_PATH=/models/whisper \
  -v /absolute/path/to/whisper-large-v3:/models/whisper \
  audio-scribe:latest \
  python mcp_server.py
```

Windows PowerShell:
```PowerShell
docker run -it --rm `
  --name audio-scribe-mcp `
  --gpus all `
  -e OPENAI_API_KEY="sk-..." `
  -e WHISPER_MODEL_PATH=/models/whisper `
  -v "D:/Development/AI/models/LLM/safetensor/whisper-large-v3-speach-to-text:/models/whisper" `
  audio-scribe:latest `
  python mcp_server.py
```

Claude Desktop example configuration (tools section) referencing this server by command:
```json
{
  "mcpServers": {
    "audio-scribe": {
      "command": "python",
      "args": ["mcp_server.py"],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "WHISPER_MODEL_PATH": "openai/whisper-large-v3"
      }
    }
  }
}
```
if run from Docker:
```json
{
  "mcpServers": {
    "audio-scribe": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "audio-scribe-mcp",
        "-e", "OPENAI_API_KEY=${env.OPENAI_API_KEY}",
        "-e", "WHISPER_MODEL_PATH=/models/whisper",
        "-v", "/path/to/your/models:/models/whisper",
        "audio-scribe-mcp:latest"
      ],
      "env": {
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

Notes:
- The MCP server operates over stdio; the client is responsible for spawning it in the working directory where audio files are accessible (or use absolute paths mounted into the container).
- For OpenAI transcription, ensure network egress is allowed.

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
