"""属地解析器注册表：按 provider 与资源就绪度选择实现。

门控口径（与 docs/api/一键刷新属地接口-2026-10-24.md 一致）：

- ``disabled`` → 503，不写库；
- ``mock``     → 干跑统计，不写库（由路由层实现，不进入本模块）；
- ``offline``  → 本模块解析 + 写库；
- ``real``     → 501（在线适配器未接入）。

IP 与手机的资源就绪度**互相独立**：IP 库缺失不应连带手机属地也不可用。
"""

from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.services.region import ip_offline, phone_offline
from app.services.region.types import RegionDataNotReady, RegionKind, ResolveOutcome

_PROVIDER_DISABLED = "disabled"
_PROVIDER_MOCK = "mock"
_PROVIDER_OFFLINE = "offline"
_PROVIDER_REAL = "real"


def provider() -> str:
    return settings.region_resolver_provider


def refresh_enabled() -> bool:
    return provider() != _PROVIDER_DISABLED


def is_ready(kind: RegionKind) -> bool:
    if kind is RegionKind.IP:
        return ip_offline.is_ready()
    return phone_offline.is_ready()


def adapter_implemented(kind: RegionKind) -> bool:
    """真实适配器是否可在当前配置下工作。"""
    return provider() == _PROVIDER_OFFLINE and is_ready(kind)


def data_version(kind: RegionKind) -> str | None:
    """数据文件版本标识（文件名 + 修改日期），供前端展示排查。"""
    path = ip_offline.resolve_db_path() if kind is RegionKind.IP else phone_offline.resolve_segment_path()
    if not path.is_file():
        return None
    return f"{path.name}@{datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d}"


def resolve(kind: RegionKind, values: list[str]) -> ResolveOutcome:
    """执行真实解析。provider 不满足时抛 ``RegionDataNotReady``。"""
    current = provider()
    if current == _PROVIDER_DISABLED:
        raise RegionDataNotReady("属地解析服务未接入（厂商未配置）")
    if current == _PROVIDER_REAL:
        raise RegionDataNotReady("在线属地适配器待接入")
    if current == _PROVIDER_MOCK:
        raise RegionDataNotReady("mock provider 不执行真实解析")
    if current != _PROVIDER_OFFLINE:
        raise RegionDataNotReady(f"未知的属地 provider：{current}")
    if kind is RegionKind.IP:
        return ip_offline.resolve_many(values)
    return phone_offline.resolve_many(values)
