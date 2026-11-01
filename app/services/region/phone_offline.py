"""手机号 → 归属地（离线号段表）。

号段表是外部资产（工信部码号资源按批次公示，建议月度更新），格式见
``data/region/phone_segment.sample.csv``：``prefix,province,city,isp,updated_at``。

解析顺序：7 位前缀精确匹配 → 4 位前缀降级 → 未命中计入 unknown（**不写"未知"**）。
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path

from app.core.config import settings
from app.services.region.types import RegionDataNotReady, ResolveOutcome

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, tuple[str, str]]]] = {}


def default_segment_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "region" / "phone_segment.csv"


def resolve_segment_path() -> Path:
    raw = (settings.region_phone_segment_path or "").strip()
    return Path(raw) if raw else default_segment_path()


def normalize_phone(raw: str | None) -> str | None:
    """归一到 11 位大陆手机号；不可用返回 ``None``（计入 skipped）。"""
    if not raw:
        return None
    value = str(raw).strip()
    for token in (" ", "-", "\t", "(", ")", "\u3000"):
        value = value.replace(token, "")
    if value.startswith("+86"):
        value = value[3:]
    elif value.startswith("0086"):
        value = value[4:]
    elif value.startswith("86") and len(value) == 13:
        value = value[2:]
    if not value.isdigit() or len(value) != 11 or not value.startswith("1") or value[1] not in "3456789":
        return None
    return value


def _format(province: str, city: str) -> str:
    if not city or city == province:
        return province
    return f"{province}{city}"


def _load_table(path: Path) -> dict[str, tuple[str, str]]:
    if not path.is_file():
        raise RegionDataNotReady(f"手机号段表未就绪：{path}")
    mtime = path.stat().st_mtime
    cached = _CACHE.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    with _LOCK:
        cached = _CACHE.get(str(path))
        if cached is not None and cached[0] == mtime:
            return cached[1]
        table: dict[str, tuple[str, str]] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            if not {"prefix", "province", "city"}.issubset(fields):
                raise RegionDataNotReady("号段表缺少必需列：prefix/province/city")
            for row in reader:
                prefix = (row.get("prefix") or "").strip()
                province = (row.get("province") or "").strip()
                city = (row.get("city") or "").strip()
                if not prefix.isdigit() or not province:
                    continue
                table[prefix] = (province, city)
        if not table:
            raise RegionDataNotReady("号段表内容为空")
        _CACHE[str(path)] = (mtime, table)
        return table


def is_ready() -> bool:
    path = resolve_segment_path()
    return path.is_file() and path.stat().st_size > 0


def resolve_many(values: list[str]) -> ResolveOutcome:
    table = _load_table(resolve_segment_path())
    resolved: dict[str, str] = {}
    skipped = 0
    unknown = 0
    for value in values:
        phone = normalize_phone(value)
        if phone is None:
            skipped += 1
            continue
        region: str | None = None
        for size in (7, 4):
            entry = table.get(phone[:size])
            if entry is not None:
                region = _format(*entry)
                break
        if region is None:
            unknown += 1
            continue
        resolved[value] = region
    return ResolveOutcome(resolved=resolved, skipped=skipped, unknown=unknown)
