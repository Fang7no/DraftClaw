from draftclaw._runtime.paragraph_chunker import ParagraphChunker


def test_paragraph_chunker_balances_by_character_length() -> None:
    chunker = ParagraphChunker(target_chunks=2)
    text = f"{'A' * 20}\n\nbb\n\ncc\n\ndd"

    chunks, infos = chunker.split(text)

    assert len(chunks) == 2
    assert chunks[0] == "A" * 20
    assert chunks[1] == "bb\n\ncc\n\ndd"
    assert [info.paragraph_count for info in infos] == [1, 3]
    assert [info.char_count for info in infos] == [20, 10]


def test_paragraph_chunker_uses_five_chunks_when_possible() -> None:
    chunker = ParagraphChunker()
    text = "\n\n".join(f"p{idx}" for idx in range(1, 11))

    chunks, infos = chunker.split(text)

    assert len(chunks) == 5
    assert [info.paragraph_count for info in infos] == [2, 2, 2, 2, 2]
    assert chunks[0] == "p1\n\np2"
    assert chunks[-1] == "p9\n\np10"


def test_paragraph_chunker_caps_chunk_count_to_paragraphs() -> None:
    chunker = ParagraphChunker(target_chunks=5)

    chunks, infos = chunker.split("only one")

    assert len(chunks) == 1
    assert len(infos) == 1
    assert infos[0].paragraph_count == 1


def test_paragraph_chunker_auto_uses_one_chunk_for_short_text() -> None:
    chunker = ParagraphChunker(target_chunks=0)

    chunks, infos = chunker.split("alpha\n\nbeta")

    assert len(chunks) == 1
    assert len(infos) == 1
    assert infos[0].paragraph_count == 2


def test_paragraph_chunker_auto_picks_upper_odd_number_on_tie() -> None:
    chunker = ParagraphChunker(target_chunks=0)
    paragraph = "a" * 3332
    text = "\n\n".join([paragraph, paragraph, paragraph])

    chunks, infos = chunker.split(text)

    assert len(chunks) == 3
    assert len(infos) == 3
    assert [info.paragraph_count for info in infos] == [1, 1, 1]


def test_paragraph_chunker_auto_caps_to_nineteen_chunks() -> None:
    chunker = ParagraphChunker(target_chunks=0)
    paragraph = "a" * 5000
    text = "\n\n".join(paragraph for _ in range(25))

    chunks, infos = chunker.split(text)

    assert len(chunks) == 19
    assert len(infos) == 19
