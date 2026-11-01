"""属地（IP / 手机号）解析与批量刷新。

设计约束（务必保持）：

- 本包**不写库**的结论除外均集中在 ``refresh.py``：写库 SQL 只允许出现在那里，
  以便 ``matchmaker_crm_admin._refresh_region`` 源码保持"不含 UPDATE users SET ip_region"
  的既有断言（tests/test_member_lifecycle_gap_fill_20261024.py::test_region_refresh_gating_and_dry_run）。
- 数据文件缺失时一律抛 ``RegionDataNotReady``，由路由层转成 503，
  **绝不**用占位或"未知"写进展示列（写错比不写更糟）。
"""

from app.services.region.types import RegionDataNotReady, RegionKind, ResolveOutcome

__all__ = ["RegionDataNotReady", "RegionKind", "ResolveOutcome"]
