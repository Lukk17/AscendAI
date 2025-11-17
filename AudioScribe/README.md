# AudioScribe

AudioScribe is a versatile, dynamic speech-to-text service supporting local, OpenAI, and Hugging Face models. The transcription model is chosen **per-request**, allowing for maximum flexibility.

---
### API Documentation

The REST API is self-documenting via Swagger and Redoc. While the server is running, you can access:

*   **Swagger UI**: [http://localhost:7017/docs](http://localhost:7017/docs)
*   **Redoc**: [http://localhost:7017/redoc](http://localhost:7017/redoc)

---

## Prerequisites

*   **Python 3.11**
*   **Nvidia CUDA**
    * https://developer.nvidia.com/cuda-12-6-0-download-archive
    * https://developer.nvidia.com/cudnn-downloads
*   **PyTorch**
    * https://pytorch.org/get-started/locally/ 
*   **ffmpeg**: Required for audio processing.
    *   Linux: `sudo apt install ffmpeg`
    *   Windows: `choco install ffmpeg`

Python default packages repository:
https://pypi.org/

---

## Configuration (Environment Variables)

For the service to function, certain environment variables must be set.  
For local development, it is best practice to set these in your operating system's environment variables,  
as they include secrets and user-specific paths.

*   `OPENAI_API_KEY`: **(Secret)** Your secret key for the OpenAI API.
*   `HF_TOKEN`: **(Secret)** Your Hugging Face token. Required for downloading models and for using the Hugging Face API provider.
*   `HF_HOME`: **(Local Path)** The directory where Hugging Face will cache downloaded models. This prevents re-downloading large models every time.

**Example `HF_HOME` and Model Parameter:**

If you set your `HF_HOME` environment variable to `D:\Development\AI\hf-cache`,  
the `transformers` library will automatically use this folder.  
When you make an API request, you still use the public model *identifier* in the `model` field.  
The library handles the mapping.

*   **Environment Variable:** `HF_HOME=D:\Development\AI\hf-cache`
*   **API `model` parameter:** `openai/whisper-large-v3`

---

## Running the Service

### Running as a standard Python App (without Docker)

This method is suitable for local development.  
Ensure you have set the **environment variables** mentioned above.

1.  **Install Dependencies:**
    In `./AudioScribe` directory in terminal:

    ```shell
    python -m venv .venv
    ```
    Activate the virtual environment
    Windows
    ```PowerShell
    .\.venv\Scripts\activate.ps1
    ```
    Unix
    ```shell
    ./.venv/bin/activate
    ```
    Install PyTorch separately from its specific index
    ```shell
    pip install --index-url https://download.pytorch.org/whl/cu121 "torch==2.5.1+cu121"
    ```
    Install all other application requirements
    ```shell
    pip install -r pytorch-requirements.txt -r requirements.txt
    ```
    without cache:
    ```shell
    pip install --no-cache-dir -r pytorch-requirements.txt -r requirements.txt
    ```

2.  **Run the Uvicorn Server:**
    ```shell
    uvicorn main:app --host 0.0.0.0 --port 7017 --reload
    ```

### Running with Docker (Recommended)

This is the recommended method for a stable deployment.

**1. Build the Docker image:**
```shell
# Build the main image for the REST API
docker build -t audio-scribe:latest .

# Or, build the image for the MCP server
docker build -f Dockerfile.mcp -t audio-scribe-mcp:latest .
```

**2. Run the container:**

**For Linux/macOS:**
```shell
docker run -d \
  --name audio-scribe \
  --gpus all \
  -p 7017:7017 \
  -e OPENAI_API_KEY="sk-..." \
  -e HF_TOKEN="hf_..." \
  -e HF_HOME=/hf-cache \
  -v ~/hf-cache:/hf-cache \
  audio-scribe:latest
```

**For Windows (PowerShell):**
```PowerShell
docker run -d `
  --name audio-scribe `
  --gpus all `
  -p 7017:7017 `
  -e OPENAI_API_KEY="sk-..." `
  -e HF_TOKEN="hf_..." `
  -e HF_HOME=/hf-cache `
  -v "D:/path/to/your/hf-cache:/hf-cache" `
  audio-scribe:latest
```
*   `--gpus all`: **Required** for local transcription to run on the GPU.
*   `-v ...:/hf-cache`: **Recommended**. Mounts a local directory to cache models.

---

## Making API Requests

You specify the model in the body of your `POST` request.

**Example using `curl` for local transcription:**

**For Linux/macOS:**
```shell
curl -X POST "http://localhost:7017/api/v1/transcribe/local" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@$HOME/Desktop/audio.wav" \
  -F "model=openai/whisper-large-v3"
```

**For Windows (Command Prompt):**
```cmd
curl -X POST "http://localhost:7017/api/v1/transcribe/local" ^
  -H "Content-Type: multipart/form-data" ^
  -F "file=@%USERPROFILE%\Desktop\audio.wav" ^
  -F "model=openai/whisper-large-v3"
```

---

## MCP Server Mode

The MCP server runs on the same port (`7017`) and uses the same unified container. It also accepts the model per-request.

**Exposed MCP Tools:**
*   `health()`
*   `transcribe_local(file_path: str, model: str)`
*   `transcribe_openai(file_path: str, model: str)`
*   `transcribe_hf(file_path: str, model: str)`

### Example MCP Client Configurations

To use these tools, configure your AI-powered editor or client to connect to the running server's URL.

**For Claude Desktop / Generic Clients:**
```json
{
  "mcpServers": {
    "audio-scribe": {
      "url": "http://localhost:7017"
    }
  }
}
```

---

## Dependencies

To update dependency versions in `requirements.txt` excluding ones which should be manually updated,  
due to torch compatibility  
Windows:
```PowerShell
pip freeze | Select-String -NotMatch -Pattern '^(torch|numpy|sympy|networkx|mpmath|filelock|fsspec|jinja2|typing_extensions)$' > requirements.txt
```
Unix:
```shell
pip freeze | grep -v -E '^(torch|numpy|sympy|networkx|mpmath|filelock|fsspec|jinja2|typing_extensions)$' > requirements.txt
```

---
## Troubleshooting

### Checking lib versions

#### nvidia drivers
```shell
nvidia-smi
```
#### torch
```python
import torch
print(torch.cuda.is_available())
```

#### cudnn

```python
import torch
print(torch.backends.cudnn.version())
```

### Hugging Face Symlinks Warning on Windows

When running the application on Windows, you may see a `UserWarning` about symlinks not being supported.

**Why it happens:** The `huggingface_hub` library uses symbolic links by default to efficiently manage its cache. Standard user accounts on Windows cannot create symlinks without special permissions. This is a warning, not an error, and the cache will still function, but it may take up more disk space.

**Solution 1 (Recommended): Set Environment Variable**

The easiest way to resolve this is to disable the warning by setting an environment variable:
```
HF_HUB_DISABLE_SYMLINKS_WARNING=1
```

**Solution 2: Enable Developer Mode**

Alternatively, you can enable Developer Mode on Windows to allow your user account to create symlinks.
1.  Open **Settings**.
2.  Go to **System** > **Advanced** > **For developers**.
3.  Toggle **Developer Mode** to **On**.
You may need to restart your terminal or IDE for the change to take effect.

---

### Reinstalling python dependencies
Terminal in your activated virtual environment.  

This creates a temporary list of everything that's currently installed.
```shell
pip freeze > temp_requirements.txt
```
Now, use that list to uninstall everything.  
The -y flag automatically confirms all the uninstallations so you don't have to do it one by one.
```shell
pip uninstall -y -r temp_requirements.txt
```
Then reinstall:
```shell
pip install --no-cache-dir -r pytorch-requirements.txt -r requirements.txt
```
Now you can remove `temp_requirements.txt` file.