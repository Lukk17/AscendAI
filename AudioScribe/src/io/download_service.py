import aiofiles
import aiohttp
import os
from urllib.parse import urlparse
from urllib.request import url2pathname

from src.io.file_service import create_temp_file, safe_suffix_from_filename


async def download_to_temp_async(uri: str) -> str:
    """
    Async download from URI to a temp file.
    Supports:
      - file:// (copies local file to temp)
      - http://, https:// (downloads to temp)
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    if scheme == "file" or not scheme:
        # Handle local file
        # url2pathname handles Windows paths (e.g. /C:/foo -> C:\foo)
        source_path = url2pathname(parsed.path)
        
        # Basic validation
        if not os.path.exists(source_path):
             raise ValueError(f"File not found: {source_path}")

        suffix = safe_suffix_from_filename(source_path)
        temp_path = create_temp_file(suffix)

        # Copy content using aiofiles
        async with aiofiles.open(source_path, 'rb') as src:
            content = await src.read()
        
        async with aiofiles.open(temp_path, 'wb') as dst:
            await dst.write(content)

        return temp_path

    elif scheme in ("http", "https"):
        # Handle HTTP/HTTPS
        suffix = safe_suffix_from_filename(parsed.path)
        temp_path = create_temp_file(suffix)

        async with aiohttp.ClientSession() as session:
            async with session.get(uri) as response:
                if response.status != 200:
                    # Clean up empty temp file if download fails
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    raise ValueError(f"Failed to download from {uri}: {response.status}")
                
                content = await response.read()

        async with aiofiles.open(temp_path, 'wb') as out_file:
            await out_file.write(content)

        return temp_path

    else:
        raise ValueError(f"Unsupported URI scheme: {scheme}")
