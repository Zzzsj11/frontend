"""提示词注册中心：运行时为生成链路解析「当前已发布」的提示词版本。

读取顺序：进程内缓存（60s TTL）→ DB 已发布版本 → 内置默认（defaults.py）。
任何 DB 异常或渲染异常都回退内置默认，保证生成链路永不因提示词配置问题中断。
后台发布/回滚后调用 invalidate() 立即失效缓存。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from ..database import session_factory
from ..models import PromptTemplateModel, PromptVersionModel
from .defaults import DEFAULT_PROMPTS

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60.0
_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptRenderError(ValueError):
    """模板变量缺失（渲染参数不含模板声明的变量）。"""


def template_variables(content: str) -> list[str]:
    """提取模板中全部 {{var}} 变量名（去重排序）。"""
    return sorted(set(_VAR_PATTERN.findall(content)))


def render_template(content: str, values: dict[str, Any]) -> str:
    missing = [name for name in template_variables(content) if name not in values]
    if missing:
        raise PromptRenderError(f"缺少模板变量：{', '.join(missing)}")
    return _VAR_PATTERN.sub(lambda match: str(values[match.group(1)]), content)


def render_lenient(content: str, values: dict[str, Any]) -> str:
    """预览用宽容渲染：只替换已提供的变量，未提供的保留 {{var}} 原样。"""
    return _VAR_PATTERN.sub(lambda match: str(values[match.group(1)]) if match.group(1) in values else match.group(0), content)


@dataclass(frozen=True)
class ResolvedPrompt:
    """一次解析的结果：内容 + 来源版本。version=0 表示内置默认兜底。"""

    key: str
    content: str
    version: int
    source: str  # "db" | "builtin"
    variables: dict[str, Any] = field(default_factory=dict)
    required_fragments: list[str] = field(default_factory=list)
    format: str = "text"

    def render(self, **values: Any) -> str:
        try:
            return render_template(self.content, values)
        except PromptRenderError:
            if self.source == "builtin":
                raise
            logger.warning("prompt_render_failed key=%s version=%s，回退内置默认", self.key, self.version)
            return render_template(DEFAULT_PROMPTS[self.key]["content"], values)

    def render_json(self, **values: Any) -> Any:
        """JSON 模板渲染并解析；DB 内容损坏时回退内置默认。"""
        try:
            return json.loads(self.render(**values))
        except Exception:
            if self.source == "builtin":
                raise
            logger.warning("prompt_json_invalid key=%s version=%s，回退内置默认", self.key, self.version)
            return json.loads(render_template(DEFAULT_PROMPTS[self.key]["content"], values))


_cache: dict[str, tuple[float, ResolvedPrompt]] = {}


def invalidate(key: str | None = None) -> None:
    """使缓存失效：后台发布/回滚后调用；key=None 全量清空。"""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


async def get_prompt(key: str) -> ResolvedPrompt:
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    resolved = await _load(key)
    _cache[key] = (now, resolved)
    return resolved


async def _load(key: str) -> ResolvedPrompt:
    default = DEFAULT_PROMPTS.get(key)
    if default is None:
        raise KeyError(f"未注册的提示词 key：{key}")
    try:
        async with session_factory() as session:
            template = (await session.execute(select(PromptTemplateModel).where(PromptTemplateModel.key == key, PromptTemplateModel.deleted_at.is_(None)))).scalar_one_or_none()
            if template and template.current_version_id:
                version = await session.get(PromptVersionModel, template.current_version_id)
                if version and version.deleted_at is None and version.status == "published":
                    return ResolvedPrompt(
                        key=key,
                        content=version.content,
                        version=version.version,
                        source="db",
                        variables=template.variables or {},
                        required_fragments=template.required_fragments or [],
                        format=template.format or "text",
                    )
    except Exception as exc:  # DB 未迁移/故障时兜底内置默认，保证生成链路可用
        logger.warning("prompt_registry_load_failed key=%s err=%s，使用内置默认", key, exc)
    return ResolvedPrompt(
        key=key,
        content=default["content"],
        version=0,
        source="builtin",
        variables=default.get("variables", {}),
        required_fragments=default.get("required_fragments", []),
        format=default.get("format", "text"),
    )
