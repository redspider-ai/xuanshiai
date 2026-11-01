"""users.source（会员登记来源）归属与统计口径回归（2026-11-01）。

背景：概览页「会员登记来源占比」里大量账号显示"未填写来源"。排查发现
自助注册链路（手机号验证码 / 微信登录即注册）的 INSERT 压根没有 source 列，
只有后台建档会写；同时 source_distribution 按全量统计、页面总数按有效会员展示，
两边分母不一致。

覆盖：
- auth：手机号注册写「自己注册」；users.source 缺列时静默不写（不能挡住注册）；
  微信注册分支同口径；``_render_user_insert`` 列数与取值位数不匹配时直接抛错；
- 线索入库：admin 侧与红娘工作台侧生成的账号标「线索入库」；
- 统计：source_distribution 与会员总数同人群（排除软删、不限 status）；
- 全项目守卫：禁止再出现 ``VALUES (:{', '.join(...)})`` 这种只给首列加冒号的写法。

无真实 DB：全部走记录型桩。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app.api.dependencies import CurrentMatchmakerAdmin
from app.api.routes import matchmaker_crm_admin as crm
from app.schemas.matchmaker_admin import MatchmakerAdminAccount
from app.services import admin_home as admin_home_service
from app.services import auth as auth_service
from app.services import customer_lead_admin as lead_service
from app.services import matchmaker_workspace as workspace_service

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELF_MATCHMAKER_USER_ID = 7
ORGANIZATION_ID = 10


# --------------------------------------------------------------------- 桩


class _Result:
    def __init__(self, *, lastrowid: int = 0, rows=None, first=None, one=None, scalar=None) -> None:
        self.lastrowid = lastrowid
        self._rows = list(rows or [])
        self._first = first
        self._one = one
        self._scalar = scalar

    def mappings(self) -> "_Result":
        return self

    def all(self) -> list:
        return self._rows

    def first(self):
        return self._first

    def one(self):
        return self._one

    def scalar(self):
        return self._scalar


class _Ctx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc) -> bool:
        return False


class _StubDb:
    """按顺序吐出预置结果，并记录压平后的 (sql, params)。"""

    def __init__(self, results: list[_Result] | None = None) -> None:
        self.statements: list[tuple[str, dict]] = []
        self._results = list(results or [])

    async def execute(self, stmt, params=None):  # noqa: ANN001
        self.statements.append((" ".join(str(stmt).split()), dict(params or {})))
        return self._results.pop(0) if self._results else _Result()

    async def scalar(self, stmt):  # noqa: ANN001
        self.statements.append((" ".join(str(stmt).split()), {}))
        return None

    def begin(self) -> _Ctx:
        return _Ctx()

    def begin_nested(self) -> _Ctx:
        return _Ctx()

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


def _admin(scope: str) -> CurrentMatchmakerAdmin:
    return CurrentMatchmakerAdmin(
        account=MatchmakerAdminAccount(
            id=1, username="admin", display_name="Admin",
            matchmaker_user_id=SELF_MATCHMAKER_USER_ID, data_scope=scope,
            organization_id=ORGANIZATION_ID, status=1, last_login_at=None,
        ),
        session_id=1,
        permissions=frozenset(),
    )


def _insert_users(db: _StubDb) -> tuple[str, dict]:
    matches = [item for item in db.statements if item[0].startswith("INSERT INTO users")]
    assert matches, db.statements
    return matches[0]


def _bound_names(sql: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r":(\w+)", sql)}


# --------------------------------------------------------------------- auth


@pytest.mark.asyncio
async def test_phone_registration_marks_source_self_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _open(_db) -> bool:  # noqa: ANN001
        return True

    async def _noop(*_a, **_k) -> None:
        return None

    async def _columns(_db):  # noqa: ANN001
        return frozenset({"source", "phone"})

    monkeypatch.setattr(auth_service, "platform_registration_open", _open)
    monkeypatch.setattr(auth_service, "ensure_default_user_role", _noop)
    monkeypatch.setattr(auth_service, "_users_columns", _columns)
    db = _StubDb([_Result(first=None), _Result(lastrowid=101)])

    assert await auth_service.get_or_create_user_by_phone(db, "13800000000", "1.2.3.4") == 101

    sql, params = _insert_users(db)
    assert "source" in sql.split("VALUES")[0]
    assert params["source"] == "自己注册"
    # 每个绑定变量都要有对应参数，反向亦然：漏一列就会退化成裸列名引用。
    assert _bound_names(sql) == set(params)


@pytest.mark.asyncio
async def test_phone_registration_skips_source_when_column_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """迁移未执行的环境不能因为一句 Unknown column 把新用户挡在注册流程外。"""

    async def _open(_db) -> bool:  # noqa: ANN001
        return True

    async def _noop(*_a, **_k) -> None:
        return None

    async def _columns(_db):  # noqa: ANN001
        return frozenset({"phone"})

    monkeypatch.setattr(auth_service, "platform_registration_open", _open)
    monkeypatch.setattr(auth_service, "ensure_default_user_role", _noop)
    monkeypatch.setattr(auth_service, "_users_columns", _columns)
    db = _StubDb([_Result(first=None), _Result(lastrowid=102)])

    await auth_service.get_or_create_user_by_phone(db, "13800000000", None)

    sql, params = _insert_users(db)
    assert "source" not in sql
    assert "source" not in params
    assert _bound_names(sql) == set(params)


def test_wechat_registration_uses_the_same_source_path() -> None:
    src = inspect.getsource(auth_service.login_wechat)
    assert 'if "source" in await _users_columns(db)' in src
    assert 'values.append(":source")' in src
    assert "SOURCE_SELF_REGISTER" in src


def test_render_user_insert_rejects_column_value_mismatch() -> None:
    with pytest.raises(ValueError, match="不一致"):
        auth_service._render_user_insert(["phone", "source"], [":phone"])
    rendered = auth_service._render_user_insert(["phone", "source"], [":phone", ":source"])
    assert rendered == "INSERT INTO users (phone, source) VALUES (:phone, :source)"


# --------------------------------------------------------------------- 线索入库


def test_admin_lead_convert_marks_source_from_lead() -> None:
    src = inspect.getsource(lead_service.convert_lead)
    assert '"source" in await _table_columns(db, "users")' in src
    assert 'user_values.append(":source")' in src
    assert "SOURCE_FROM_LEAD" in src
    assert lead_service.SOURCE_FROM_LEAD == "线索入库"


def test_workspace_lead_convert_marks_source_from_lead() -> None:
    src = inspect.getsource(workspace_service.convert_workspace_lead)
    assert "await _users_has_source(db)" in src
    assert 'user_values.append(":source")' in src
    assert "SOURCE_FROM_LEAD" in src
    assert workspace_service.SOURCE_FROM_LEAD == "线索入库"


def test_workspace_member_entry_marks_source_matchmaker() -> None:
    """服务红娘录入的会员不能落到「未填写来源」里，字典中本来就有「红娘录入」一档。"""
    src = inspect.getsource(workspace_service.create_workspace_member)
    assert 'user_values["source"] = SOURCE_MATCHMAKER_ENTRY' in src
    assert workspace_service.SOURCE_MATCHMAKER_ENTRY == "红娘录入"


def test_workspace_source_probe_is_shared_not_duplicated() -> None:
    """users.source 探测必须只有一处实现，避免后续新增建账号入口漏接。"""
    src = inspect.getsource(workspace_service)
    assert src.count("AND COLUMN_NAME = 'source'") == 1


# --------------------------------------------------------------------- 统计口径


@pytest.mark.asyncio
async def test_source_distribution_shares_member_total_population() -> None:
    """来源分布必须与会员统计同一人群：排除软删、不限 status。

    2026-11-01 定案。之前先拿 status=1 做分母、又拿全量做总数，概览页同时出现
    「登记总数 33 / 男女相加 32 / 来源相加 20」三个互不相等的数。
    """
    keys = ("total", "male", "female", "vip", "active", "unassigned",
            "never_followed", "follow_due_today", "abandoned")
    db = _StubDb([
        # _available_columns 现在先于主查询执行（两处 SQL 都要靠它判定 deleted_at）。
        _Result(rows=[("users", "source"), ("users", "deleted_at")]),
        _Result(one={key: 0 for key in keys}),
        _Result(rows=[]),
    ])

    stats = await crm.member_statistics(current=_admin("STORE"), db=db)

    assert stats.source_distribution == []
    total_sql = db.statements[1][0]
    dist_sql = db.statements[-1][0]
    assert "GROUP BY value" in dist_sql, "取到的不是来源分布 SQL"
    for name, sql in (("total", total_sql), ("distribution", dist_sql)):
        assert "u.deleted_at IS NULL" in sql, f"{name} 未排除软删会员"
        # 允许 SUM(u.status = 1) active 这类指标列，但不能拿它当人群过滤条件。
        assert "AND u.status = 1" not in sql, f"{name} 不应按有效会员过滤（与列表页口径不一致）"


def _metric_line(src: str, name: str) -> str:
    matches = [line for line in src.splitlines() if line.strip().endswith(f") {name},")]
    assert matches, f"未找到 {name} 的统计 SQL 行"
    return matches[0]


def test_dashboard_member_metrics_exclude_soft_deleted() -> None:
    """概览的会员总数/男女必须与会员列表同人群（排除软删、不限 status）。

    否则同一页面会同时出现三个互不相等的分母：登记总数 33（全表）、
    男女相加 32（1 个未填性别）、来源相加 20（status=1）。
    """
    src = inspect.getsource(admin_home_service.dashboard)
    for name in ("member_count", "male_member_count", "female_member_count"):
        line = _metric_line(src, name)
        assert "deleted_at IS NULL" in line, f"{name} 未排除软删会员：{line}"
        assert "status = 1" not in line, f"{name} 不应限定 status=1：{line}"


def test_dashboard_platform_user_count_includes_soft_deleted() -> None:
    """「平台用户」是累计注册口径，必须含已删除账号（2026-11-01 定案：33 vs 31）。

    它与会员总数是两个不同指标，不是漏加过滤；曾经两边都拼 deleted_at 导致两卡同值，
    于是「删了多少会员」在概览上看不出来。锁住防止后续被「统一口径」改回去。
    """
    src = inspect.getsource(admin_home_service.dashboard)
    platform_line = _metric_line(src, "platform_user_count")
    member_line = _metric_line(src, "member_count")
    assert "deleted_at" not in platform_line, f"平台用户不应排除软删：{platform_line}"
    assert "deleted_at IS NULL" in member_line, "会员总数必须排除软删"


# --------------------------------------------------------------------- 全项目守卫


def test_no_bare_colon_join_left_in_any_values_clause() -> None:
    """``VALUES (:{', '.join(cols)})`` 只会给第一列加冒号，其余列被 MySQL 当列引用。

    2026-10-31 客源录入/导入就是这个写法造成「201 成功但资料全 null」，
    这里做静态守卫，防止同类拼接在别处复活。
    """
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in (PROJECT_ROOT / "app").rglob("*.py")
        if "VALUES (:{" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
