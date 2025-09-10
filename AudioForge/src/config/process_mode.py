from enum import Enum


class ProcessMode(str, Enum):
    CONVERT = "convert"
    TRIM = "trim"
    FULL = "full"
