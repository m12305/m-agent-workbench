"""InProcessTaskQueue — asyncio.create_task 实现"""

import asyncio
import uuid
import logging
from datetime import datetime

from .base import TaskStatus, TaskInfo
from .worker import TaskWorker
from ..repositories.base import TaskRepository

logger = logging.getLogger("server.task_queue")


class InProcessTaskQueue:

    def __init__(self, worker: TaskWorker, task_repo: TaskRepository):
        self._worker = worker
        self._repo = task_repo

    async def enqueue(self, document_id: str) -> str:
        task_id = str(uuid.uuid4())[:8]
        task = TaskInfo(task_id=task_id, document_id=document_id)
        await self._repo.save(task)
        asyncio.create_task(self._run(task))
        return task_id

    async def get(self, task_id: str) -> TaskInfo | None:
        return await self._repo.get(task_id)

    async def _run(self, task: TaskInfo):
        try:
            await self._worker.execute(task.document_id)
            task.status = TaskStatus.DONE.value
            task.progress = 1.0
        except Exception as e:
            logger.error("任务失败: task=%s, error=%s", task.task_id, e)
            task.status = TaskStatus.FAILED.value
            task.error_message = str(e)
        finally:
            task.updated_at = datetime.utcnow()
            await self._repo.save(task)
