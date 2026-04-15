"""
Chunk splitting utilities.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from config import CHUNK_MAX_SIZE, CHUNK_MIN_SIZE
from logger import AgentLogger


@dataclass
class Chunk:
    """A contiguous slice of the parsed markdown."""

    id: int
    content: str
    char_count: int
    start_pos: int
    end_pos: int


class ChunkSplitter:
    """Split long text into paragraph-aligned chunks."""

    def __init__(
        self,
        min_size: int = CHUNK_MIN_SIZE,
        max_size: int = CHUNK_MAX_SIZE,
        logger: Optional[AgentLogger] = None,
    ):
        self.min_size = min_size
        self.max_size = max_size
        self.logger = logger

    def split(self, text: str) -> List[Chunk]:
        if self.logger:
            self.logger.log(
                "Chunker",
                "input",
                data={
                    "text_length": len(text),
                    "min_size": self.min_size,
                    "max_size": self.max_size,
                },
                input_data={"text_preview": text[:3000] + "..." if len(text) > 3000 else text},
                message="Starting text chunking",
            )

        if not text:
            return []

        if len(text) <= self.max_size:
            chunk = Chunk(
                id=0,
                content=text.strip(),
                char_count=len(text.strip()),
                start_pos=0,
                end_pos=len(text),
            )
            if self.logger:
                self.logger.log(
                    "Chunker",
                    "output",
                    data={
                        "chunk_count": 1,
                        "chunks": [
                            {
                                "id": chunk.id,
                                "char_count": chunk.char_count,
                                "start_pos": chunk.start_pos,
                                "end_pos": chunk.end_pos,
                            }
                        ],
                    },
                    output_data={"chunks_content": {"chunk_0": chunk.content[:1500] + "..." if len(chunk.content) > 1500 else chunk.content}},
                    message="Chunking completed with 1 chunk",
                )
            return [chunk]

        paragraph_spans = self._split_paragraph_spans(text)
        grouped_spans = self._group_paragraph_spans(paragraph_spans)
        chunks = self._build_chunks_from_spans(text, grouped_spans)

        if self.logger:
            chunk_info = [
                {
                    "id": chunk.id,
                    "char_count": chunk.char_count,
                    "start_pos": chunk.start_pos,
                    "end_pos": chunk.end_pos,
                }
                for chunk in chunks
            ]
            chunks_content = {
                f"chunk_{chunk.id}": chunk.content[:1500] + "..." if len(chunk.content) > 1500 else chunk.content
                for chunk in chunks
            }
            self.logger.log(
                "Chunker",
                "output",
                data={"chunk_count": len(chunks), "chunks": chunk_info},
                output_data={"chunks_content": chunks_content},
                message=f"Chunking completed with {len(chunks)} chunks",
            )

        return chunks

    @staticmethod
    def _split_paragraph_spans(text: str) -> List[Tuple[int, int]]:
        separator_pattern = re.compile(r"\n[ \t]*\n+")
        spans: List[Tuple[int, int]] = []
        block_start = 0

        for match in separator_pattern.finditer(text):
            block_end = match.end()
            if text[block_start:block_end].strip():
                spans.append((block_start, block_end))
            block_start = block_end

        if block_start < len(text) and text[block_start:].strip():
            spans.append((block_start, len(text)))

        return spans or [(0, len(text))]

    def _group_paragraph_spans(self, paragraph_spans: List[Tuple[int, int]]) -> List[List[Tuple[int, int]]]:
        grouped: List[List[Tuple[int, int]]] = []
        current_group: List[Tuple[int, int]] = []
        current_size = 0

        for span_start, span_end in paragraph_spans:
            paragraph_size = span_end - span_start
            if not current_group:
                current_group = [(span_start, span_end)]
                current_size = paragraph_size
                continue

            if current_size + paragraph_size <= self.max_size or current_size < self.min_size:
                current_group.append((span_start, span_end))
                current_size += paragraph_size
                continue

            grouped.append(current_group)
            current_group = [(span_start, span_end)]
            current_size = paragraph_size

        if current_group:
            grouped.append(current_group)

        if len(grouped) >= 2:
            last_group_size = sum(end - start for start, end in grouped[-1])
            if last_group_size < self.min_size:
                grouped[-2].extend(grouped[-1])
                grouped.pop()

        return grouped

    @staticmethod
    def _build_chunks_from_spans(text: str, grouped_spans: List[List[Tuple[int, int]]]) -> List[Chunk]:
        chunks: List[Chunk] = []

        for chunk_id, span_group in enumerate(grouped_spans):
            raw_start = span_group[0][0]
            raw_end = span_group[-1][1]
            raw_content = text[raw_start:raw_end]
            trimmed_content = raw_content.strip()
            if not trimmed_content:
                continue

            leading_trim = len(raw_content) - len(raw_content.lstrip())
            trailing_trim = len(raw_content) - len(raw_content.rstrip())
            start_pos = raw_start + leading_trim
            end_pos = raw_end - trailing_trim
            chunks.append(
                Chunk(
                    id=chunk_id,
                    content=trimmed_content,
                    char_count=len(trimmed_content),
                    start_pos=start_pos,
                    end_pos=end_pos,
                )
            )

        return chunks
