"""a14: `FakeMlService` tất định + có ngữ nghĩa; đi qua `MlClient` thật (retry, đếm ở nơi nhận)."""

import pytest
from app.core.clock import FakeClock
from tests.fakes.fake_ml import FakeMlService, cosine, embed_text

pytestmark = pytest.mark.asyncio

Q_VPN = "Không kết nối được VPN, báo lỗi chứng chỉ hết hạn"
P_VPN = "Chứng chỉ VPN hết hạn thì không kết nối được: vào ứng dụng VPN, chọn gia hạn chứng chỉ."
P_MFA = "Đăng ký MFA: cài ứng dụng xác thực trên điện thoại rồi quét mã QR trên cổng tài khoản."


async def test_a14_deterministic_and_semantic() -> None:
    fake = FakeMlService()
    ml = fake.client()
    first = await ml.embed([Q_VPN, P_VPN, P_MFA])
    second = await ml.embed([Q_VPN])
    assert first.data is not None and second.data is not None
    q, vpn, mfa = first.data.vectors
    assert q == second.data.vectors[0] == embed_text(Q_VPN)  # cùng câu → cùng vector
    assert cosine(q, vpn) > cosine(q, mfa)
    assert first.data.dim == 1024 and len(q) == 1024


async def test_a14_rerank_semantic_in_unit_interval() -> None:
    r = await FakeMlService().client().rerank(Q_VPN, [P_MFA, P_VPN])
    assert r.data is not None
    mfa, vpn = r.data.scores
    assert 0.0 <= mfa < vpn <= 1.0


async def test_fail_next_goes_through_real_client_retry() -> None:
    fake = FakeMlService().fail_next("rerank", "timeout", 2)
    clock = FakeClock()
    r = await fake.client(clock).rerank(Q_VPN, [P_VPN])
    assert r.error is None and r.attempts == 2 and fake.calls["rerank"] == 3
    fake.fail_next("rerank", "http_500", 3)
    r = await fake.client(clock).rerank(Q_VPN, [P_VPN])
    assert (r.error, r.attempts) == ("http_5xx", 3)


async def test_model_missing_and_classifiers() -> None:
    fake = FakeMlService().fail_next("embed", "model_missing")
    r = await fake.client().embed(["a"])
    assert (r.error, r.attempts, fake.calls["embed"]) == ("model_missing", 0, 1)
    c = await fake.client().classify_intent("vpn lỗi")
    assert c.error == "model_missing" and fake.calls["classify_intent"] == 1


async def test_truncate_all_flag() -> None:
    r = await FakeMlService(truncate_all=True).client().embed(["ngắn"])
    assert r.data is not None and r.data.truncated == [True]
    rr = await FakeMlService(truncate_all=True).client().rerank("q", ["p"])
    assert rr.data is not None and rr.data.query_truncated and rr.data.truncated == [True]
