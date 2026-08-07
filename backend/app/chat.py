from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from openai import AsyncOpenAI
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from .config import settings
from .database import session_factory
from .models import ChatMessageModel, ChatSessionModel
from .redis_store import append_chat_event, chat_events_after, redis


@dataclass
class ChatSession:
    id: str
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
            system_prompt=model.system_prompt,
            title=model.title,
            status=model.status,
            created_at=model.created_at.timestamp(),
            messages=messages,
        )

    async def create(self, system_prompt: str) -> ChatSession:
        model = ChatSessionModel(id=f"chat-{uuid.uuid4().hex}", system_prompt=system_prompt)
        async with session_factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return ChatSession(
            id=model.id,
            system_prompt=model.system_prompt,
            title=model.title,
            status=model.status,
            created_at=model.created_at.timestamp(),
            messages=[],
        )

    async def get(self, session_id: str) -> ChatSession | None:
        async with session_factory() as session:
            result = await session.execute(
                select(ChatSessionModel)
                .where(ChatSessionModel.id == session_id)
                .options(selectinload(ChatSessionModel.messages))
            )
            model = result.scalar_one_or_none()
        if not model:
            return None
        item = self._from_model(model)
        item.last_seq = int(await redis.get(f"chat:{session_id}:seq") or 0)
        return item

    async def list(self) -> list[dict[str, Any]]:
        async with session_factory() as session:
            result = await session.execute(select(ChatSessionModel).order_by(ChatSessionModel.created_at.desc()))
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

    async def delete(self, session_id: str) -> bool:
        task = self.tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        async with session_factory() as session:
            model = await session.get(ChatSessionModel, session_id)
            if not model:
                return False
            await session.delete(model)
            await session.commit()
        await redis.delete(f"chat:{session_id}:seq", f"chat:{session_id}:events")
        return True

    async def post(self, session: ChatSession, text: str) -> int:
        task = self.tasks.get(session.id)
        if task and not task.done():
            raise RuntimeError("助手仍在回复，请等待或先中断")
        async with session_factory() as db:
            model = await db.get(ChatSessionModel, session.id)
            if not model:
                raise RuntimeError("对话不存在")
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
                text = "".join(
                    block.get("text", "")
                    for block in body.get("content", [])
                    if block.get("type") == "text"
                )
                if text:
                    chunks.append(text)
                    await append_chat_event(session.id, "assistant_delta", {"text": text})
            else:
                client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
                stream = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[{"role": "system", "content": session.system_prompt}, *session.messages],
                    stream=True,
                )
                async for chunk in stream:
                    text = chunk.choices[0].delta.content if chunk.choices else None
                    if text:
                        chunks.append(text)
                        await append_chat_event(session.id, "assistant_delta", {"text": text})
            answer = "".join(chunks)
            async with session_factory() as db:
                db.add(ChatMessageModel(session_id=session.id, role="assistant", content=answer))
                await db.commit()
            await append_chat_event(session.id, "assistant_done", {"text": answer})
        except asyncio.CancelledError:
            await append_chat_event(session.id, "interrupted", {})
        except Exception as exc:
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

    async def events_after(self, session_id: str, after: int) -> list[dict[str, Any]]:
        return await chat_events_after(session_id, after)


chat_manager = ChatManager()
