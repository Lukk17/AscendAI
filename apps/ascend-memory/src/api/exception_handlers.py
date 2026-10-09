from ascend_python_common.errors import INTERNAL, VALIDATION, ErrorRegistry


def build_error_registry() -> ErrorRegistry:
    registry = ErrorRegistry(internal_code=INTERNAL)
    registry.register(ValueError, VALIDATION, str)
    return registry


error_registry = build_error_registry()
