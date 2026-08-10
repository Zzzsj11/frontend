from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from .config import settings
from .database import session_factory
from .models import ChatMessageModel, ChatSessionModel
from .redis_store import append_chat_event, chat_events_after, redis
from .token_usage import add_token_usage
from .usage_quota import consume_daily_quota


@dataclass
class ChatSession:
    id: str
    user_id: str
    system_prompt: str
    title: str
    status: str
    created_at: float
    messages: list[dict[str, str]] = field(default_factory=list)
    last_seq: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "createdAt": self.created_at,
            "lastSeq": self.last_seq,
        }


class ChatManager:
    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    def _from_model(model: ChatSessionModel) -> ChatSession:
        messages = [{"role": item.role, "content": item.content} for item in model.messages]
        return ChatSession(
            id=model.id,
            user_id=model.user_id or "",
            system_prompt=model.system_prompt,
            title=model.title,
            status=model.status,
            created_at=model.created_at.timestamp(),
            messages=messages,
        )

    async def create(self, user_id: str, system_prompt: str) -> ChatSession:
        model = ChatSessionModel(id=f"chat-{uuid.uuid4().hex}", user_id=user_id, system_prompt=system_prompt)
        async with session_factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return ChatSession(
            id=model.id,
            user_id=user_id,
            system_prompt=model.system_prompt,
            title=model.title,
            status=model.status,
            created_at=model.created_at.timestamp(),
            messages=[],
        )

    async def get(self, user_id: str, session_id: str) -> ChatSession | None:
        async with session_factory() as session:
            result = await session.execute(
                select(ChatSessionModel)
                .where(ChatSessionModel.id == session_id, ChatSessionModel.user_id == user_id, ChatSessionModel.deleted_at.is_(None))
                .options(selectinload(ChatSessionModel.messages))
            )
            model = result.scalar_one_or_none()
        if not model:
            return None
        item = self._from_model(model)
        item.last_seq = int(await redis.get(f"chat:{session_id}:seq") or 0)
        return item

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        async with session_factory() as session:
            result = await session.execute(
                select(ChatSessionModel).where(ChatSessionModel.user_id == user_id, ChatSessionModel.deleted_at.is_(None)).order_by(ChatSessionModel.created_at.desc())
            )
            models = result.scalars().all()
        return [
            {
                "id": model.id,
                "title": model.title,
                "status": model.status,
                "createdAt": model.created_at.timestamp(),
                "lastSeq": int(await redis.get(f"chat:{model.id}:seq") or 0),
            }
            for model in models
        ]

    async def delete(self, user_id: str, session_id: str) -> bool:
        task = self.tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        async with session_factory() as session:
            model = await session.get(ChatSessionModel, session_id)
            if not model or model.user_id != user_id or model.deleted_at is not None:
                return False
            model.deleted_at = datetime.now().astimezone()
            await session.execute(
                update(ChatMessageModel).where(ChatMessageModel.session_id == session_id, ChatMessageModel.deleted_at.is_(None)).values(deleted_at=model.deleted_at)
            )
            await session.commit()
        await redis.delete(f"chat:{session_id}:seq", f"chat:{session_id}:events")
        return True

    async def post(self, session: ChatSession, text: str, *, daily_limit: int) -> int:
        task = self.tasks.get(session.id)
        if task and not task.done():
            raise RuntimeError("助手仍在回复，请等待或先中断")
        async with session_factory() as db:
            model = await db.get(ChatSessionModel, session.id)
            if not model:
                raise RuntimeError("对话不存在")
            await consume_daily_quota(db, user_id=session.user_id, category="chat", limit=daily_limit)
            if not session.messages:
                model.title = text.splitlines()[0][:60]
            model.status = "running"
            db.add(ChatMessageModel(session_id=session.id, role="user", content=text))
            await db.commit()
        session.messages.append({"role": "user", "content": text})
        user_event = await append_chat_event(session.id, "user", {"text": text})
        await append_chat_event(session.id, "state", {"status": "running"})
        self.tasks[session.id] = asyncio.create_task(self._run(session))
        return user_event["seq"]

    async def _run(self, session: ChatSession) -> None:
        usage: Any = {}
        request_id: str | None = None
        usage_recorded = False
        try:
            if not settings.llm_api_key:
                raise RuntimeError("LLM_API_KEY 未配置")
            chunks: list[str] = []
            if settings.llm_api_mode == "anthropic":
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        f"{settings.llm_base_url.rstrip('/')}/v1/messages",
                        headers={
                            "x-api-key": settings.llm_api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": settings.llm_model,
                            "system": session.system_prompt,
                            "messages": session.messages,
                            "max_tokens": 2048,
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    usage = body.get("usage") or {}
                    request_id = body.get("id")
                text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
                if text:
                    chunks.append(text)
                    await append_chat_event(session.id, "assistant_delta", {"text": text})
            else:
                client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
                stream = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[{"role": "system", "content": session.system_prompt}, *session.messages],
                    stream=True,
                    stream_options={"include_usage": True},
                )
                async for chunk in stream:
                    if chunk.usage:
                        usage = chunk.usage
                    request_id = request_id or getattr(chunk, "id", None)
                    text = chunk.choices[0].delta.content if chunk.choices else None
                    if text:
                        chunks.append(text)
                        await append_chat_event(session.id, "assistant_delta", {"text": text})
            answer = "".join(chunks)
            async with session_factory() as db:
                db.add(ChatMessageModel(session_id=session.id, role="assistant", content=answer))
                _, normalized_usage = add_token_usage(
                    db,
                    operation="chat",
                    provider=settings.llm_api_mode,
                    model=settings.llm_model,
                    usage=usage,
                    user_id=session.user_id,
                    chat_session_id=session.id,
                    request_id=request_id,
                )
                await db.commit()
                usage_recorded = True
            await append_chat_event(session.id, "assistant_done", {"text": answer, "usage": normalized_usage})
        except asyncio.CancelledError:
            if not usage_recorded:
                async with session_factory() as db:
                    add_token_usage(
                        db,
                        operation="chat_cancelled",
                        provider=settings.llm_api_mode,
                        model=settings.llm_model,
                        usage=usage,
                        user_id=session.user_id,
                        chat_session_id=session.id,
                        request_id=request_id,
                    )
                    await db.commit()
            await append_chat_event(session.id, "interrupted", {})
        except Exception as exc:
            if not usage_recorded:
                async with session_factory() as db:
                    add_token_usage(
                        db,
                        operation="chat_failed",
                        provider=settings.llm_api_mode,
                        model=settings.llm_model,
                        usage=usage,
                        user_id=session.user_id,
                        chat_session_id=session.id,
                        request_id=request_id,
                    )
                    await db.commit()
            await append_chat_event(session.id, "error", {"text": str(exc)})
        finally:
            async with session_factory() as db:
                model = await db.get(ChatSessionModel, session.id)
                if model:
                    model.status = "idle"
                    await db.commit()
            await append_chat_event(session.id, "state", {"status": "idle"})

    async def interrupt(self, session_id: str) -> None:
        task = self.tasks.get(session_id)
        if task and not task.done():
            task.cancel()

    async def events_after(self, user_id: str, session_id: str, after: int) -> list[dict[str, Any]]:
        if not await self.get(user_id, session_id):
            return []
        return await chat_events_after(session_id, after)


chat_manager = ChatManager()
