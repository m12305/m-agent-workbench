"""检索服务 — 查询向量化 + Milvus 搜索 + 结果格式化"""

import logging
from ..milvus.client import MilvusClient, SearchResult

logger = logging.getLogger("server.retrieval")


class RetrievalService:
    """知识库检索服务。

    流程:
      1. 用户 query → Embedding 向量化
      2. Milvus 向量搜索 (按 scope + user_id 过滤)
      3. 返回格式化片段列表
    """

    def __init__(
        self,
        embedding_service,
        milvus_client: MilvusClient,
    ):
        self._embedding = embedding_service
        self._milvus = milvus_client

    async def search(
        self,
        query: str,
        scope: str = "hybrid",
        user_id: str = "",
        top_k: int = 8,
    ) -> list[SearchResult]:
        """检索知识库。

        Args:
            query: 用户问题
            scope: 检索范围 — "private" / "shared" / "hybrid"
            user_id: 当前用户 ID (private 过滤必需)
            top_k: 每种范围返回数量

        Returns:
            去重后的 SearchResult 列表，按 relevance 排序
        """
        if not self._embedding or not self._milvus:
            logger.warning("Embedding 或 Milvus 未配置，返回空结果")
            return []

        # 1. 向量化查询 — 优先使用 embed_query 以提升召回质量
        if hasattr(self._embedding, "embed_query"):
            embed_results = await self._embedding.embed_query([query])
            embed_result = embed_results[0]
        else:
            embed_result = await self._embedding.embed_single(query)
        query_vector = embed_result.vector
        logger.debug("查询向量化完成: dim=%d, tokens=%d",
                      len(query_vector), embed_result.tokens)

        # 2. 按范围检索
        if scope == "hybrid":
            # 分别检索 private + shared，合并去重
            private_hits = self._milvus.search(
                query_vector, top_k=top_k,
                scope="private", user_id=user_id,
            )
            shared_hits = self._milvus.search(
                query_vector, top_k=top_k,
                scope="shared",
            )
            hits = self._dedupe_and_merge(private_hits, shared_hits, top_k)
        else:
            hits = self._milvus.search(
                query_vector, top_k=top_k,
                scope=scope, user_id=user_id if scope == "private" else "",
            )

        logger.info("检索完成: scope=%s, hits=%d", scope, len(hits))
        return hits

    def _dedupe_and_merge(
        self,
        private: list[SearchResult],
        shared: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """去重并混合排序。

        按 chunk_id 去重，保留高分版本。合并后取 Top N。
        """
        seen: set[str] = set()
        merged: list[SearchResult] = []

        # 按分数降序排列，高分的先占位
        for hit in sorted(private + shared, key=lambda h: h.score, reverse=True):
            if hit.chunk_id not in seen:
                seen.add(hit.chunk_id)
                merged.append(hit)

        # 按分数排序取 Top K
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[:top_k * 2]  # hybrid 返回两倍量，后续可由 Reranker 精排

    @staticmethod
    def format_context(hits: list[SearchResult]) -> str:
        """将检索结果格式化为 LLM 上下文文本。

        Returns:
            可直接注入 prompt 的格式文本
        """
        if not hits:
            return ""

        lines = ["\n--- 知识库检索结果 ---\n"]
        for i, h in enumerate(hits, 1):
            scope_label = "私人" if h.scope == "private" else "公共"
            source = f"[{i}] {h.source_name} ({scope_label}"
            if h.page_start:
                source += f" 第{h.page_start}页"
            source += ")"
            lines.append(f"{source}\n{h.text}\n")

        return "\n".join(lines)
