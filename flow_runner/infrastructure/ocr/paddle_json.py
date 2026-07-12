from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PIL.Image import Image

from flow_runner.domain.errors import ConditionError
from flow_runner.infrastructure.ocr.base import OcrItem, OcrObservation


class PaddleJsonClient(Protocol):
    async def recognize(self, image: Image) -> list[dict[str, Any]]: ...


class PaddleJsonProcessClient:
    def __init__(
        self,
        executable: Path,
        *,
        process_factory: Callable[..., Any] = subprocess.Popen,
        shutdown_timeout_seconds: float = 3.0,
    ) -> None:
        self.executable = executable.resolve()
        self.process_factory = process_factory
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.process: Any | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if not self.executable.is_file():
            raise FileNotFoundError(self.executable)
        self.process = self.process_factory(
            [str(self.executable)],
            cwd=str(self.executable.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    async def recognize(self, image: Image) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._recognize_sync, image.copy())

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self.shutdown_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=self.shutdown_timeout_seconds)

    def _recognize_sync(self, image: Image) -> list[dict[str, Any]]:
        temporary = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image_path = Path(temporary.name)
        temporary.close()
        try:
            image.save(image_path)
            with self._lock:
                self.start()
                process = self.process
                if process is None or process.stdin is None or process.stdout is None:
                    raise RuntimeError("PaddleOCR-json process pipes are unavailable")
                process.stdin.write(
                    json.dumps({"image_path": str(image_path)}, ensure_ascii=False) + "\n"
                )
                process.stdin.flush()
                while True:
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError("PaddleOCR-json closed its output stream")
                    try:
                        response = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(response, dict):
                        continue
                    code = int(response.get("code", -1))
                    data = response.get("data")
                    if code == 101:
                        return []
                    if code != 100:
                        raise RuntimeError(str(data or response))
                    if isinstance(data, list):
                        return [dict(row) for row in data]
        finally:
            image_path.unlink(missing_ok=True)


class PaddleJsonOcr:
    name = "paddle-json"

    def __init__(self, client: PaddleJsonClient) -> None:
        self.client = client

    async def recognize(
        self,
        image: Image,
        *,
        language: str,
        preprocessing: str,
    ) -> OcrObservation:
        del language, preprocessing
        try:
            rows = await self.client.recognize(image)
            items = [_normalize_row(row) for row in rows]
        except Exception as error:
            raise ConditionError(f"PaddleOCR-json failed: {error}") from error
        return OcrObservation(text=" ".join(item.text for item in items), items=items)


def _normalize_row(row: dict[str, Any]) -> OcrItem:
    points = row["box"]
    xs = [int(point[0]) for point in points]
    ys = [int(point[1]) for point in points]
    return OcrItem(
        text=str(row["text"]),
        bounds=(min(xs), min(ys), max(xs), max(ys)),
        confidence=float(row["score"]),
    )
