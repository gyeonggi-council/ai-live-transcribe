"""채널 목록 API 계약 고정 — 채널 정의를 코드 상수에서 DB 로 옮기기 전/후가 같음을 증명한다.

이 파일은 **전환 전에 먼저 쓰고** 전환 후 그대로 통과해야 한다.
`/api/channels` 는 프런트(`hooks/useChannels.ts`·`types/index.ts:84-97`)와 설치형 추출기가 읽는
공개 계약이라, 필드가 하나라도 빠지면 화면이 조용히 빈다.
"""

from fastapi.testclient import TestClient

from app.core.channels import SEED_CHANNELS

REQUIRED_FIELDS = {"id", "name", "code", "stream_url"}


def test_channel_list_shape_and_order(client: TestClient):
    res = client.get("/api/channels")
    assert res.status_code == 200
    items = res.json()

    # 개수·순서가 시드와 같다 (정렬 기준이 바뀌면 /live 의 채널 탭 순서가 뒤집힌다)
    assert [c["id"] for c in items] == [c["id"] for c in SEED_CHANNELS]

    for ch in items:
        assert REQUIRED_FIELDS <= set(ch), f"{ch.get('id')} 에 필수 필드가 빠졌다"
        assert isinstance(ch["id"], str) and ch["id"]
        # meetings.channel_id 가 VARCHAR(20) 이다 — 넘치면 회의 생성이 실패한다
        assert len(ch["id"]) <= 20


def test_known_channels_survive(client: TestClient):
    """운영에서 실제로 쓰이는 채널이 사라지지 않았는지 — 본회의와 외부 스트림 시험 채널."""
    by_id = {c["id"]: c for c in client.get("/api/channels").json()}
    assert by_id["ch14"]["name"] == "본회의"
    assert by_id["ch14"]["code"] == "A011"
    assert "chT1" in by_id


def test_committee_falls_back_to_name():
    """`committee` 를 따로 주지 않으면 위원회명 = 채널명. 명부 매칭이 이 값에 걸려 있다."""
    from app.core.channels import get_committee_for_channel

    assert get_committee_for_channel("ch7") == "안전행정위원회"
    assert get_committee_for_channel("없는채널") is None
