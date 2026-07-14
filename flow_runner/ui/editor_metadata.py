COMMON_FIELDS: dict[str, frozenset[str]] = {
    "vision.ocr": frozenset({"target", "region", "keywords"}),
    "input.mouse": frozenset({"operation", "position", "button", "clicks"}),
    "input.keyboard": frozenset({"operation", "key", "keys", "text", "count"}),
    "system.wait": frozenset({"seconds"}),
    "system.launch": frozenset({"path", "arguments", "run_as_admin"}),
    "system.window_action": frozenset({"operation", "title", "geometry"}),
}


def common_fields_for(capability: str) -> frozenset[str] | None:
    return COMMON_FIELDS.get(capability)
