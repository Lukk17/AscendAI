
# AudioForge

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

```

Windows PowerShell
```powershell

```

### Curl

```powershell
curl -X POST "http://localhost:7018/process-full?sample_rate=16000&output_format=wav" `
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
.\AudioForge\.venv\Scripts\activate
```

---