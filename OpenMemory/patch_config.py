import sys
import os

file_path = '/usr/src/openmemory/app/routers/config.py'

if not os.path.exists(file_path):
    print(f"Error: File not found at {file_path}")
    sys.exit(1)

lines = open(file_path).readlines()
try:
    idx = [i for i, l in enumerate(lines) if 'class EmbedderConfig(BaseModel):' in l][0]
    lines.insert(idx+1, '    class Config:\n        extra = "allow"\n')
    open(file_path, 'w').writelines(lines)
    print(f"Successfully patched {file_path}")
except IndexError:
    print(f"Error: Target class 'EmbedderConfig' not found in {file_path}")
    sys.exit(1)
