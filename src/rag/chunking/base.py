"""分块策略协议 + Chunk 数据模型"""

import uuid
import hashlib
from datetime import datetime
from dataclasses import dataclass, field
from typing import Protocol

from ..parsing.base import ParsedDocument


@dataclass
class Chunk:
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    chunk_index: int = 0
    chunk_hash: str = ""
    text: str = ""
    page_start: int = 1
    page_end: int = 1
    sections: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.chunk_hash and self.text:
            self.chunk_hash = hashlib.sha256(self.text.encode()).hexdigest()


class ChunkingStrategy(Protocol):

    @property
    def name(self) -> str: ...

    def chunk(self, parsed: ParsedDocument, document_id: str) -> list[Chunk]: ...
