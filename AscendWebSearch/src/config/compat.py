import logging
import sys

logger = logging.getLogger(__name__)

class Compat(dict):
    """
    Compatibility Shim (Smart Dictionary).

    This class mimics a dictionary to resolve version conflicts between 'crawlee' and 'browserforge'.
    'crawlee' (v1.3.1) expects 'browserforge' to have a 'DATA_FILES' mapping, which was removed in 'browserforge' v1.2.4.

    This shim intercepts key lookups (filenames) and returns them as-is, preventing 'crawlee' from crashing
    when it tries to look up file paths. It uses a heuristic to differentiate between 'headers' and 'fingerprints'.
    """
    def __init__(self, category: str):
        self.category = category
        super().__init__()

    def __contains__(self, key):
        # Heuristic: headers/input usually go to headers dir
        if self.category == 'headers':
            return "header" in str(key) or "input" in str(key)
        return False # fingerprints will be caught by the else block in crawlee

    def __getitem__(self, key):
        return key

def apply_compatibility_patches():
    """
    Applies runtime patches to fix incompatibilities between 3rd party libraries.
    Current fixes:
    - browserforge vs crawlee: Injects missing DATA_FILES attribute.
    """
    try:
        import browserforge.download
        if not hasattr(browserforge.download, 'DATA_FILES'):
            logger.warning("Compatibility: Patching browserforge.download.DATA_FILES for crawlee support.")
            # Shim to prevent crawlee crash.
            # Crawlee logic: if name in headers -> use headers path, else -> use fingerprints path.
            browserforge.download.DATA_FILES = {
                'headers': Compat('headers'),
                'fingerprints': Compat('fingerprints')
            }
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Compatibility Patch Failed: {e}")
