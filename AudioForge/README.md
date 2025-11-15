
# AudioForge

---
## OpenApi documentation

Swagger
http://localhost:7018/docs#/

Redoc
http://localhost:7018/redoc

---

## Temporary files
1. **Windows**  
    Stored in the user's temp directory `C:\Users\[username]\AppData\Local\Temp`

2. **Linux**  
    Usually stored in `/tmp`

3. **Docker**  
    Stored inside the container's filesystem in `/tmp`, which will be cleared when the container is restarted,  
    but could fill up during container runtime

---

## Prerequisites

### Windows libs
Admin terminal:
```powershell
choco install sox.portable
```
```powershell
choco install ffmpeg
```

### Python
Version 3.13

Create [Virtual environment](#Virtual-environment)

### Installing python dependencies

[Active correct(!) venv](#activate-venv)

Using `requirements.txt` file  

```shell
python.exe -m pip install --upgrade pip
```
PyTorch (CUDA 12.1)
```shell
pip install "mutagen==1.47.0" "colorlog==6.9.0"
```
```shell
pip install -r requirements.txt
```

Manually
```shell
python.exe -m pip install --upgrade pip
```
```shell
pip install "fastapi==0.116.1" "uvicorn==0.35.0" "python-multipart==0.0.20"
```

---
## Run
Run with port selection:

### Local
User run configuration in `.run` directory named `Audioforge`

Or run from the terminal
```shell
uvicorn main:app --host 0.0.0.0 --port 7018 --reload
```

### Docker

#### Build docker image
```shell
docker build -t audio-forge:latest .
```

#### Run docker image

Linux:
```shell
docker run -d \
  --name audio-forge \
  -p 7018:7018 \
  audio-forge:latest
```

Windows PowerShell
```powershell
docker run -d `
  --name audio-forge `
  -p 7018:7018 `
  audio-forge:latest
```

### OpenApi documentation

```
http://localhost:7018/docs
```

### Curl

```powershell
curl -X POST "http://localhost:7018/api/v1/audio/process?mode=full&output_format=wav&sample_rate=16000&silence_duration=0.5&silence_threshold=0.05" `
  -F "file=@C:\Users\Lukk\Desktop\recording.flac" `
  -o processed_audio.wav
```

```powershell
curl --location 'http://localhost:7018/convert?output_format=wav&sample_rate=16000' `
  --form 'file=@C:\Users\Lukk\Desktop\recording.flac' `
  -o converted_audio.wav
```

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
C:\Python313\python.exe -m venv .venv
```

#### Activate venv
Windows:
```powershell
.\AudioForge\.venv\Scripts\activate.ps1
```
Linux:
```shell
./AudioForge/.venv/Scripts/activate
```

---

---

## Run as an MCP server (Model Context Protocol)

AudioForge can also run as an MCP server so AI agents and compatible editors (e.g., Claude Desktop) can call its tools directly.

Prerequisites:
- Ensure ffmpeg and sox are installed and available in PATH (same as for the regular setup).
- Install the MCP Python SDK dependency (already listed in requirements.txt as `mcp`).

Local run:
```shell
python mcp_server.py
```
This starts an MCP server over stdio. MCP-aware clients will spawn it and communicate via stdio.

Exposed MCP tools:
- health() -> "ok"
- convert_audio(file_path: str, output_format?: str, sample_rate?: int) -> JSON with: source, operation, output_path, media_type, filename
- remove_silence(file_path: str, silence_duration?: str, silence_threshold?: str) -> JSON with: source, operation, output_path, media_type, filename
- process_full(file_path: str, output_format?: str, sample_rate?: int, silence_duration?: str, silence_threshold?: str) -> JSON with: source, operation, output_path, media_type, filename

Docker (MCP mode):
Use the same image but override the command to run the MCP server instead of FastAPI.

Linux:
```shell
docker run -it --rm \
  --name audio-forge-mcp \
  -v /absolute/path/to/audio-files:/data \
  audio-forge:latest \
  python mcp_server.py
```

Windows PowerShell:
```PowerShell
docker run -it --rm `
  --name audio-forge-mcp `
  -v "D:/path/to/audio-files:/data" `
  audio-forge:latest `
  python mcp_server.py
```

Claude Desktop example configuration (tools section) referencing this server by command:
```json
{
  "mcpServers": {
    "audio-forge": {
      "command": "python",
      "args": ["mcp_server.py"]
    }
  }
}
```

Notes:
- The MCP server operates over stdio; the client is responsible for spawning it in the working directory where audio files are accessible (or use absolute paths mounted into the container).
- Output files are written to temporary directories; capture the returned output_path to retrieve the processed file.
