from __future__ import annotations

import re
from math import inf
from typing import Sequence

from draftclaw._core.contracts import ChunkInfo


class ParagraphChunker:
    def __init__(self, separator_regex: str = r"\n\s*\n", target_chunks: int = 5) -> None:
        self.separator_regex = separator_regex
        self.target_chunks = target_chunks

    def split(self, text: str) -> tuple[list[str], list[ChunkInfo]]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        paragraphs = [p.strip() for p in re.split(self.separator_regex, normalized) if p.strip()]
        if not paragraphs:
            raise ValueError("No paragraphs found in text")

        target_chunks = self._resolve_target_chunks(normalized)
        chunk_count = min(target_chunks, len(paragraphs))
        groups = self._distribute(paragraphs, chunk_count)

        chunks: list[str] = []
        infos: list[ChunkInfo] = []
        cursor = 1
        for idx, group in enumerate(groups, start=1):
            chunk_text = "\n\n".join(group)
            start_para = cursor
            end_para = cursor + len(group) - 1
            cursor = end_para + 1
            chunks.append(chunk_text)
            infos.append(
                ChunkInfo(
                    chunk_id=idx,
                    start_paragraph=start_para,
                    end_paragraph=end_para,
                    paragraph_count=len(group),
                    char_count=len(chunk_text),
                    token_estimate=max(1, len(chunk_text) // 4),
                )
            )
        return chunks, infos

    def _resolve_target_chunks(self, normalized_text: str) -> int:
        if self.target_chunks > 0:
            return self.target_chunks

        char_ratio = len(normalized_text) / 5000
        odd_candidates = range(1, 20, 2)
        return min(odd_candidates, key=lambda candidate: (abs(candidate - char_ratio), -candidate))

    @staticmethod
    def _distribute(paragraphs: Sequence[str], chunk_count: int) -> list[list[str]]:
        if chunk_count <= 0:
            raise ValueError("chunk_count must be positive")

        paragraph_lengths = [len(paragraph) for paragraph in paragraphs]
        prefix = [0]
        for length in paragraph_lengths:
            prefix.append(prefix[-1] + length)

        total_chars = ParagraphChunker._segment_char_count(prefix, 0, len(paragraphs))
        target_chars = total_chars / chunk_count

        dp = [[inf] * (len(paragraphs) + 1) for _ in range(chunk_count + 1)]
        cuts = [[0] * (len(paragraphs) + 1) for _ in range(chunk_count + 1)]
        dp[0][0] = 0.0

        for group_count in range(1, chunk_count + 1):
            for end in range(group_count, len(paragraphs) + 1):
                best_cost = inf
                best_start = group_count - 1
                for start in range(group_count - 1, end):
                    segment_chars = ParagraphChunker._segment_char_count(prefix, start, end)
                    deviation = segment_chars - target_chars
                    cost = dp[group_count - 1][start] + deviation * deviation
                    if cost < best_cost:
                        best_cost = cost
                        best_start = start
                dp[group_count][end] = best_cost
                cuts[group_count][end] = best_start

        boundaries: list[tuple[int, int]] = []
        end = len(paragraphs)
        for group_count in range(chunk_count, 0, -1):
            start = cuts[group_count][end]
            boundaries.append((start, end))
            end = start
        boundaries.reverse()

        return [list(paragraphs[start:end]) for start, end in boundaries]

    @staticmethod
    def _segment_char_count(prefix: Sequence[int], start: int, end: int) -> int:
        paragraph_count = end - start
        if paragraph_count <= 0:
            return 0
        raw_chars = prefix[end] - prefix[start]
        separator_chars = (paragraph_count - 1) * 2
        return raw_chars + separator_chars
