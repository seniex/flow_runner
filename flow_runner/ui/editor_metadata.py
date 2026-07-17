COMMON_FIELDS: dict[str, frozenset[str]] = {
    "vision.ocr": frozenset({"target", "region", "keywords"}),
    "input.mouse": frozenset({"target", "operation", "position", "button", "clicks"}),
    "input.keyboard": frozenset({"operation", "key", "keys", "text", "count"}),
    "system.wait": frozenset({"seconds"}),
    "system.launch": frozenset({"path", "arguments", "run_as_admin"}),
    "system.window": frozenset({"process_name", "fallback_process_names", "require_foreground"}),
    "system.window_action": frozenset(
        {"operation", "process_name", "fallback_process_names", "geometry"}
    ),
}


def common_fields_for(capability: str) -> frozenset[str] | None:
    return COMMON_FIELDS.get(capability)
