from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any


class HybridRetrievalService:
    def score_documents(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int = 10,
    ) -> list[dict[str, Any]]:
        if not documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        corpus_tokens = [self._tokenize(str(doc.get("content", ""))) for doc in documents]
        if not any(corpus_tokens):
            return []

        doc_freq: defaultdict[str, int] = defaultdict(int)
        for tokens in corpus_tokens:
            for token in set(tokens):
                doc_freq[token] += 1

        doc_count = len(corpus_tokens)
        avgdl = sum(len(tokens) for tokens in corpus_tokens) / max(doc_count, 1)
        scored: list[dict[str, Any]] = []
        for document, tokens in zip(documents, corpus_tokens, strict=True):
            if not tokens:
                continue
            score = self._bm25_score(
                query_tokens=query_tokens,
                doc_tokens=tokens,
                doc_freq=doc_freq,
                doc_count=doc_count,
                avgdl=avgdl,
            )
            if score <= 0:
                continue
            scored.append({**document, "bm25_score": score})

        scored.sort(key=lambda item: item["bm25_score"], reverse=True)
        for item in scored:
            item["score"] = float(item.get("bm25_score", 0.0))
        return scored[:top_n]

    def _bm25_score(
        self,
        *,
        query_tokens: list[str],
        doc_tokens: list[str],
        doc_freq: defaultdict[str, int],
        doc_count: int,
        avgdl: float,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> float:
        tf = Counter(doc_tokens)
        score = 0.0
        doc_len = len(doc_tokens)
        for token in query_tokens:
            if token not in tf:
                continue
            df = doc_freq.get(token, 0)
            if df == 0:
                continue
            idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
            numerator = tf[token] * (k1 + 1)
            denominator = tf[token] + k1 * (1 - b + b * doc_len / max(avgdl, 1e-6))
            score += idf * numerator / denominator
        return score

    def _tokenize(self, text: str) -> list[str]:
        normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower()).strip()
        if not normalized:
            return []

        tokens: list[str] = []
        for part in normalized.split():
            if re.fullmatch(r"[\u4e00-\u9fff]+", part):
                if len(part) <= 2:
                    tokens.append(part)
                    continue
                tokens.append(part)
                tokens.extend(part[i : i + 2] for i in range(len(part) - 1))
            else:
                tokens.append(part)
        return [token for token in tokens if token]
