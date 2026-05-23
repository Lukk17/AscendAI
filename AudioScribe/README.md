# AudioScribe

A dynamic speech-to-text service supporting local (faster-whisper), OpenAI, and Hugging Face models. The
transcription backend is chosen **per request** so the same deployment can serve all three.

---

### Table of Contents

- [API Documentation](#api-documentation)
- [Agent Skill](#agent-skill)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Running the Service](#running-the-service)
- [Making API Requests](#making-api-requests)
- [MCP Server Mode](#mcp-server-mode)
- [Dependencies](#dependencies)
- [Troubleshooting](#troubleshooting)
- [Docs map](#docs-map)

---

### API Documentation

The REST API is self-documenting via Swagger and Redoc. While the server is running:

- **Swagger UI**: [http://localhost:7017/docs](http://localhost:7017/docs)
- **Redoc**: [http://localhost:7017/redoc](http://localhost:7017/redoc)

---

### Agent Skill

A drop-in skill ships at [skills/audio-scribe/SKILL.md](skills/audio-scribe/SKILL.md). Copy
[skills/audio-scribe/](skills/audio-scribe/) into your agent's skills folder (`.claude/skills/`, `.agents/skills/`,
`.opencode/skills/`, etc.) and the agent will pick it up automatically.

The skill covers the four endpoints (`/local`, `/openai`, `/hf`, `/audacity`), backend-selection guidance (when to
use which), the streaming SSE flow with `download_url`, and the multi-track Audacity / Craig-Bot zip workflow. Base
URL is intentionally left out (varies per environment); the agent runtime provides it.

When you change endpoint shapes here, update the SKILL.md so downstream agents stay accurate.

---

### Prerequisites

- **Python 3.11**
- **Nvidia CUDA 12.6** ([download](https://developer.nvidia.com/cuda-12-6-0-download-archive))
- **cuDNN 9.x** ([download](https://developer.nvidia.com/cudnn-downloads))
- **PyTorch** with CUDA 12.6 builds ([install guide](https://pytorch.org/get-started/locally/))
- **ffmpeg** for audio processing

Linux cuDNN install (Ubuntu 24.04):

```bash
wget https://developer.download.nvidia.com/compute/cudnn/9.16.0/local_installers/cudnn-local-repo-ubuntu2404-9.16.0_1.0-1_amd64.deb
```

```bash
sudo dpkg -i cudnn-local-repo-ubuntu2404-9.16.0_1.0-1_amd64.deb
```

```bash
sudo cp /var/cudnn-local-repo-ubuntu2404-9.16.0/cudnn-*-keyring.gpg /usr/share/keyrings/
```

```bash
sudo apt-get update
```

```bash
sudo apt-get -y install cudnn9-cuda-12
```

ffmpeg install. Linux:

```bash
sudo apt install ffmpeg
```

Windows:

```powershell
choco install ffmpeg
```

Python packages live on [pypi.org](https://pypi.org).

---

### Configuration

Settings live in [src/config/config.py](src/config/config.py) (pydantic-settings, reads `.env` automatically). For
local development, set these in your OS environment so they survive shell restarts and don't end up in source control:

- `OPENAI_API_KEY`. (Secret) OpenAI API key. See [platform.openai.com](https://platform.openai.com/settings/organization/api-keys).
- `HF_TOKEN`. (Secret) Hugging Face token. Required for downloading models and for the Hugging Face provider.
  See [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
- `HF_HOME`. Local directory where Hugging Face caches downloaded models. Prevents re-downloading large models
  every restart.

When you POST a transcription request you still pass the public model identifier in the `model` field; the
`transformers` library transparently maps it to the cached files under `HF_HOME`.

Examples. Linux: add this to `~/.profile`.

```bash
export OPENAI_API_KEY="sk-..."
```

```bash
export HF_TOKEN="hf_..."
```

```bash
export HF_HOME="/mnt/01D8E3D9B5224500/Development/AI/hf-cache"
```

Windows: set `HF_HOME` in System Properties → Environment Variables, e.g. `HF_HOME=D:\Development\AI\hf-cache`.

---

### Running the Service

#### As a standard Python app

Suitable for local development. Ensure the env vars above are set first.

**1. Install dependencies.** From the `AudioScribe/` directory:

Bash:

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r pytorch-requirements.txt
```

```bash
pip install -e .[dev]
```

PowerShell:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\activate.ps1
```

```powershell
pip install -r pytorch-requirements.txt
```

```powershell
pip install -e .[dev]
```

The `-e` flag installs in editable mode so source edits show up without reinstall.

**2. Run the uvicorn server.**

Bash:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 7017 --reload
```

PowerShell:

```powershell
uvicorn src.main:app --host 0.0.0.0 --port 7017 --reload
```

#### With Docker (recommended)

**1. Build the image.**

Bash:

```bash
docker build -t audio-scribe:latest .
```

PowerShell:

```powershell
docker build -t audio-scribe:latest .
```

**2. Tag and push (optional).**

Bash:

```bash
docker tag audio-scribe:latest lukk17/audio-scribe:v0.0.1
```

```bash
docker push lukk17/audio-scribe:v0.0.1
```

PowerShell:

```powershell
docker tag audio-scribe:latest lukk17/audio-scribe:v0.0.1
```

```powershell
docker push lukk17/audio-scribe:v0.0.1
```

**3. Run the container.** `--gpus all` is required for local transcription on the GPU. `-v ~/hf-cache:/hf-cache`
mounts a host directory so the model cache survives container restarts.

Bash:

```bash
docker run -d --name audio-scribe --gpus all -p 7017:7017 -e OPENAI_API_KEY="sk-..." -e HF_TOKEN="hf_..." -e HF_HOME=/hf-cache -v ~/hf-cache:/hf-cache audio-scribe:latest
```

PowerShell:

```powershell
docker run -d --name audio-scribe --gpus all -p 7017:7017 -e OPENAI_API_KEY="sk-..." -e HF_TOKEN="hf_..." -e HF_HOME=/hf-cache -v "D:/path/to/your/hf-cache:/hf-cache" audio-scribe:latest
```

---

### Making API Requests

#### REST client

For ad-hoc testing, [mcp_requests.http](mcp_requests.http) contains ready-to-use HTTP requests for the VS Code REST
Client extension. It covers both standard API calls and MCP protocol interactions.

#### Local transcription

Uses `faster-whisper` and requires a pre-converted model.

Form fields:

- `model`. e.g. `Systran/faster-whisper-large-v3`.
- `language`. Optional, e.g. `en`, `pl`.
- `with_timestamps`. Optional `true` or `false`. Defaults to `true`.

Bash:

```bash
curl -X POST "http://localhost:7017/api/v1/transcribe/local" -H "Content-Type: multipart/form-data" -F "file=@$HOME/Desktop/audio.wav" -F "model=Systran/faster-whisper-large-v3" -F "language=en" -F "with_timestamps=false"
```

PowerShell:

```powershell
curl.exe -X POST "http://localhost:7017/api/v1/transcribe/local" -H "Content-Type: multipart/form-data" -F "file=@$env:USERPROFILE\Desktop\audio.wav" -F "model=Systran/faster-whisper-large-v3" -F "language=en" -F "with_timestamps=false"
```

#### OpenAI transcription

Form fields:

- `model`. e.g. `whisper-1`.
- `language`. Optional, e.g. `en`, `pl`.

Bash:

```bash
curl -X POST "http://localhost:7017/api/v1/transcribe/openai" -H "Content-Type: multipart/form-data" -F "file=@$HOME/Desktop/audio.wav" -F "model=whisper-1" -F "language=en"
```

PowerShell:

```powershell
curl.exe -X POST "http://localhost:7017/api/v1/transcribe/openai" -H "Content-Type: multipart/form-data" -F "file=@$env:USERPROFILE\Desktop\audio.wav" -F "model=whisper-1" -F "language=en"
```

#### Hugging Face transcription

Form fields:

- `model`. e.g. `openai/whisper-large-v3`.
- `hf_provider`. Optional, defaults to `hf-inference`.

Bash:

```bash
curl -X POST "http://localhost:7017/api/v1/transcribe/hf" -H "Content-Type: multipart/form-data" -F "file=@$HOME/Desktop/audio.wav" -F "model=openai/whisper-large-v3"
```

PowerShell:

```powershell
curl.exe -X POST "http://localhost:7017/api/v1/transcribe/hf" -H "Content-Type: multipart/form-data" -F "file=@$env:USERPROFILE\Desktop\audio.wav" -F "model=openai/whisper-large-v3"
```

---

### MCP Server Mode

The MCP server is integrated into the main application on the same port.

**Exposed MCP tools:**

- `health()`
- `transcribe_local(audio_uri, model, language, with_timestamps)`
- `transcribe_openai(audio_uri, model, language)`
- `transcribe_hf(audio_uri, model, hf_provider)`

#### How to use

Streamable HTTP (bidirectional over HTTP):

- Endpoint: `POST http://localhost:7017/mcp`
- Headers: `Content-Type: application/json` and `Accept: application/json, text/event-stream`

#### Example MCP client config

```json
{
  "mcpServers": {
    "audio-scribe": {
      "type": "streamable",
      "url": "http://localhost:7017/mcp"
    }
  }
}
```

#### Using audio URIs in MCP

The MCP tools accept an `audio_uri` argument supporting both local files and HTTP(S) URLs.

> [!NOTE]
> **Docker users (Postman).** When testing with the provided Postman collection against a Docker container, use the
> `{{audio_uri_docker}}` variable (resolves to `http://host.docker.internal:...`) instead of `{{audio_uri}}` in the
> request body. Using `localhost` from inside the container will fail.

**1. Local files (`file://`)**

Path to a file on the server's local filesystem.

- Windows: `file:///C:/Users/User/Desktop/audio.wav`
- Linux / macOS: `file:///home/user/audio.wav`
- Docker: `file:///audio/audio.wav` (ensure the file is mounted into the container)

**2. HTTP / HTTPS URLs**

The MCP server downloads HTTP / HTTPS URLs to a temporary file before processing. Useful when running in Docker or a
different environment from the audio source.

To expose a local directory to the MCP server, run `http-server` (requires Node.js):

Bash:

```bash
npm install -g http-server
```

```bash
http-server -p 9999
```

PowerShell:

```powershell
npm install -g http-server
```

```powershell
http-server -p 9999
```

If your file lives at `./audio/audio.wav` relative to where you ran the command, the URI is
`http://localhost:9999/audio/audio.wav` (or your LAN IP when accessing from a Docker container).

**3. MinIO (S3-compatible)**

If you're running the project with docker-compose, a MinIO instance is available. To make a bucket public so
AudioScribe can download files without authentication:

Exec into the MinIO container.

Bash:

```bash
docker exec -it minio /bin/sh
```

PowerShell:

```powershell
docker exec -it minio /bin/sh
```

Configure the `mc` alias (default credentials are `admin` / `password`).

Bash:

```bash
mc alias set myminio http://localhost:9000 admin password
```

```bash
mc anonymous set public myminio/public-audio
```

Upload your file via the console at `http://localhost:9071` or via `mc cp`.

Use the URI:

- Inside Docker network: `http://minio:9000/api/v1/buckets/public-audio/objects/download?prefix=audio.wav`
- From localhost: `http://localhost:9071/api/v1/buckets/public-audio/objects/download?prefix=audio.wav`

Adjust the `prefix` parameter if the file lives in a subdirectory (e.g. `prefix=test%2Faudio.wav`).

#### Example prompts

Once connected to an LLM (e.g. via AnythingLLM), trigger the tools with natural language:

> "Transcribe the audio file at `http://localhost:9999/audio/audio.wav` using the local model."

> "Please use OpenAI to transcribe this file: `file:///C:/Users/Me/Desktop/audio.wav`."

> "Transcribe `https://example.com/audio.wav` using the Hugging Face provider."

#### Tool parameters

When using the tools (MCP or direct API), specify the following parameters. Defaults differ slightly between the
standard Python app and the MCP server.

`transcribe_local`:

- `audio_uri` (MCP) / `file_path` (REST). Path or URI to the audio file.
- `model`. Path to the faster-whisper model. Default: `Systran/faster-whisper-large-v3`.
- `language`. ISO 639-1 code (e.g. `en`, `pl`). Default: `en`.
- `with_timestamps`. Boolean. MCP default `True` (returns segments with start / end times). REST default `False`
  (full text only).

`transcribe_openai`:

- `audio_uri`. Path or URI.
- `model`. OpenAI model name. Default: `whisper-1`.
- `language`. ISO 639-1 code.

`transcribe_hf`:

- `audio_uri`. Path or URI.
- `model`. Hugging Face model ID. Default: `openai/whisper-large-v3`.
- `hf_provider`. Provider type. Default: `hf-inference`.

---

### Startup readiness banner

On startup, [src/config/startup_banner.py](src/config/startup_banner.py) logs a single multi-line INFO entry with an
ANSI Shadow `AUDIO SCRIBE` banner, access URLs, API-key state for OpenAI and Hugging Face, and the list of
observability and REST endpoints. Shared convention with every other long-running service in the repo. See
[.agents/skills/coding-standards/SKILL.md](../.agents/skills/coding-standards/SKILL.md).

---

### Dependencies

The project uses a two-file approach to keep GPU builds reproducible.

- [pytorch-requirements.txt](pytorch-requirements.txt). PyTorch and related libraries pinned to CUDA 12.6 builds.
  Install this first.
- [pyproject.toml](pyproject.toml). All other dependencies with frozen versions.

To update non-PyTorch dependencies, edit [pyproject.toml](pyproject.toml).

---

### Troubleshooting

#### Checking library versions

Nvidia drivers:

```bash
nvidia-smi
```

Torch CUDA availability:

```python
import torch
print(torch.cuda.is_available())
```

cuDNN version through torch:

```python
import torch
print(torch.backends.cudnn.version())
```

#### Hugging Face symlinks warning on Windows

You may see a `UserWarning` about symlinks not being supported. The `huggingface_hub` library uses symbolic links by
default to manage its cache efficiently. Standard Windows user accounts can't create symlinks without special
permissions. It's a warning, not an error; the cache still works but uses more disk space.

Option 1 (recommended): disable the warning with an env var.

```text
HF_HUB_DISABLE_SYMLINKS_WARNING=1
```

Option 2: enable Developer Mode in Windows. Settings → System → Advanced → For developers → toggle Developer Mode on.
Restart your terminal or IDE for the change to take effect.

#### Reinstalling Python dependencies

Terminal in your activated virtual environment.

Bash:

```bash
pip freeze > uninstall.txt
```

```bash
pip uninstall -y -r uninstall.txt
```

```bash
rm uninstall.txt
```

```bash
pip install --no-cache-dir -r pytorch-requirements.txt
```

```bash
pip install --no-cache-dir .
```

PowerShell:

```powershell
pip freeze > uninstall.txt
```

```powershell
pip uninstall -y -r uninstall.txt
```

```powershell
Remove-Item uninstall.txt
```

```powershell
pip install --no-cache-dir -r pytorch-requirements.txt
```

```powershell
pip install --no-cache-dir .
```

---

### Docs map

| File                                                                       | What's in it                                                |
| :------------------------------------------------------------------------- | :---------------------------------------------------------- |
| [AGENTS.md](AGENTS.md)                                                     | Module-level instructions for AI coding agents.             |
| [pyproject.toml](pyproject.toml)                                           | Non-PyTorch deps, project version.                          |
| [pytorch-requirements.txt](pytorch-requirements.txt)                       | PyTorch pinned to CUDA 12.6 builds.                         |
| [src/main.py](src/main.py)                                                 | FastAPI app, lifespan, uvicorn entry.                       |
| [src/config/config.py](src/config/config.py)                               | Settings (OpenAI / HF / cache paths / model defaults).      |
| [src/config/startup_banner.py](src/config/startup_banner.py)               | Startup readiness banner.                                   |
| [src/transcription/](src/transcription/)                                   | Local / OpenAI / HF backends and the Audacity merger.       |
| [src/api/rest/rest_endpoints.py](src/api/rest/rest_endpoints.py)           | REST endpoints under `/api/v1/transcribe/*`.                |
| [src/api/mcp/mcp_server.py](src/api/mcp/mcp_server.py)                     | FastMCP tool definitions.                                   |
| [mcp_requests.http](mcp_requests.http)                                     | Example REST + MCP requests for the VS Code REST Client.    |
| [skills/audio-scribe/SKILL.md](skills/audio-scribe/SKILL.md)               | Drop-in agent skill for downstream agents.                  |
| [../README.md](../README.md)                                               | Monorepo overview, architecture, ports.                     |
| [../docs/architecture/README.md](../docs/architecture/README.md)           | Monorepo architecture, ADRs.                                |
