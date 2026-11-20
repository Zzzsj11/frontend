"""Temporary filesystem budgets shared by the two export runners."""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import settings


class ExportSpace:
    def __init__(self, directory: Path):
        self.directory = directory
        self.inputs: dict[int, int] = {}
        self.limit = settings.export_temp_limit_mb * 1024**2
        self.reserve = settings.export_temp_reserve_mb * 1024**2

    def download(self, key: int, received: int, declared: int | None) -> None:
        self.inputs[key] = received
        remaining = max(0, (declared or 0) - received)
        if sum(self.inputs.values()) + remaining > self.limit:
            raise ValueError("素材总量超过单次导出的临时空间限额")
        if shutil.disk_usage(self.directory).free < self.reserve + remaining:
            raise ValueError("服务器临时空间不足，请稍后重试")

    def output_limit(self, existing_output: int = 0) -> int:
        available = min(self.limit - sum(self.inputs.values()) - existing_output, shutil.disk_usage(self.directory).free - self.reserve)
        if available <= 0:
            raise ValueError("服务器没有足够的输出空间")
        return available
