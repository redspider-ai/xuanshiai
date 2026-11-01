"""会员删除兼容入口：前端会员页使用 ``/admin/love-users/{id}``（历史路径）。

语义与 ``DELETE /admin/matchmaker/members/{id}`` 完全一致：按 user_id 软删
``users.deleted_at`` + 写审计日志，敏感写同样要求 ``confirm=true`` + Idempotency-Key。
新增本路由只为补齐前端路径，不引入第二套删除逻辑。

权限靠 ``@declare_permission`` 显式声明：``matchmaker.member.manage`` 在鉴权依赖里是按 URL
里的 ``/members`` 子串推导的，而本路径是 ``/admin/love-users/…``，命中不了映射；未命中又
未声明时鉴权是 fail-closed 的，整个端点会对所有账号恒返回 403（D-5 回归拦下的就是这个）。
"""

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    CurrentMatchmakerAdmin,
    declare_permission,
    get_current_matchmaker_admin,
    require_sensitive_operation,
)
from app.api.routes.matchmaker_crm_admin import MemberDeleteResult, member_delete
from app.db.session import get_db

router = APIRouter(prefix="/admin/love-users")


@declare_permission("matchmaker.member.manage")
@router.delete(
    "/{member_id}",
    response_model=MemberDeleteResult,
    summary="删除会员（兼容路径，软删除，幂等 + 二次确认）",
)
async def love_user_delete(
    member_id: int = Path(..., ge=1),
    reason: str = Query("后台删除", min_length=1, max_length=255, description="删除理由（记入审计）"),
    idempotency_key: str = Depends(require_sensitive_operation),
    current: CurrentMatchmakerAdmin = Depends(get_current_matchmaker_admin),
    db: AsyncSession = Depends(get_db),
) -> MemberDeleteResult:
    """按 user_id 软删单个会员；越权/不存在 404，已删除 409。"""
    return await member_delete(
        member_id=member_id,
        reason=reason,
        idempotency_key=idempotency_key,
        current=current,
        db=db,
    )
