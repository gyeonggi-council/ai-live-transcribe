from app.services.sentence_buffer import SentenceBuffer


def test_buffer_accumulates_until_sentence_end():
    buf = SentenceBuffer(min_chars=5)
    assert buf.push("안녕") is None
    flushed = buf.push("하세요. ")
    assert flushed is not None
    assert "안녕하세요." in flushed


def test_buffer_flush_on_demand():
    buf = SentenceBuffer()
    buf.push("회의를 시작")
    out = buf.flush()
    assert "회의를 시작" in out
    assert buf.flush() == ""


def test_buffer_no_flush_for_short_incomplete():
    buf = SentenceBuffer(min_chars=10)
    assert buf.push("음") is None
