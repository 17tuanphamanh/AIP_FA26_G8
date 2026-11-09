"""Q4 — L-03 báo nhầm (ĐP 09/11): bớt cờ `target_is_other` bật NHẦM ở 3 chỗ, KHÔNG nới lưới an toàn cuối.

Bằng chứng (audit B3 `other_target_reason`):
(a) `device_text` — "vpn ko vao dc bao loi 809": mẫu mã máy `[a-z]{2,4}[- ]?\\d{3,5}` khớp "loi 809" khi gõ không dấu → B6 không tự suy máy
    duy nhất → hỏi mã máy (chặn luôn đường Q2 "chứng chỉ còn hạn → trả lời KB"). Cùng loại: "cong 443", "phong 302", "tang 3 phong 301".
(b) `phrase` — "… đồng nghiệp bên cạnh vẫn vào được bình thường …" (vpn): cụm "đồng nghiệp" là người để SO SÁNH, không phải đích.
(c) `identifier` — "Em quên mật khẩu AD và cài giúp em 7-Zip" (2 ý): con account dò TOÀN CÂU GỐC nhưng chỉ bỏ qua slot tài nguyên của CHÍNH
    nó → "7-zip" thành định danh người khác → hỏi "tài khoản của ai?".

Sửa (PLAN Q4, DỪNG 1):
1. Mã máy chỉ khi tiền tố ∈ `config/slots.yaml` `device_prefixes` (LAP, PC — đủ seed), không phân biệt hoa thường; MỘT nguồn cho
   `canonical_device_id`, `device_ids_in_text` (slots.py) và `device_text` + loại trừ mã máy của `identifier` (target.py). Tiền tố lạ: chỉ
   tính là mã máy trong câu khi đứng NGAY sau "máy"/"máy tính" (an toàn); slot dạng lỏng tiền tố lạ không chuẩn hoá → sai mẫu → bỏ → hỏi.
2. vpn/software (ĐP chốt 09/11 10:05): cụm CHUNG (đồng nghiệp, người khác, nhân viên mới, X ấy) bật ở MỌI vị trí, CHỈ miễn trong ngữ cảnh
   SO SÁNH: theo sau trong vài từ là "vẫn … được" / "vẫn bình thường" / "thì … được" (không có phủ định không/chưa/… xen giữa), hoặc đứng
   sau "giống/như/so với". account/access giữ nguyên.
3. Nhiều ý: bỏ qua = slot tài nguyên đã sạch của MỌI ý CHẠY ĐƯỢC trong câu (không chỉ ý đang xét); KHÔNG BAO GIỜ bỏ qua giá trị dạng mã
   nhân viên `nv\\d{3,5}`. Vẫn dò toàn câu.

Lưới cuối không đổi: fact chủ máy từ tool (`device_owner_is_requester`) + `build_ctx.target_is_other` (R11/R16/R20 đòi False) + chốt P6
ở B15 (`approval_target_unverified`) + Q2 B11 `owner_mismatch_early`. ScriptedLLM, không key, không Postgres. Seed: nv001 có đúng 1 máy
LAP-0342; LAP-0610 của nv005.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.domain.action import Action
from app.domain.risk_factors import FactorCode
from app.domain.slots import canonical_device_id, device_ids_in_text, sanitize_slots
from app.domain.states import (
    S_ASSESSING,
    S_CLARIFYING,
    S_DIAGNOSING,
    S_ESCALATED,
    S_RETRIEVING,
)
from app.domain.target import TARGET_QUESTION, target_check
from app.domain.ticket_state import ChunkRef, RiskDecision
from app.graph.nodes import (
    b03_classify,
    b06_diagnose,
    b11_slots,
    b12_assess,
    b15_prepare_approval,
    clarify_wait,
)
from app.llm.providers.scripted import Reply
from app.risk.estimator import RiskEstimate
from app.settings import SlotsFile, get_settings, get_slots, load_slots
from pydantic import ValidationError
from tests.fakes.risk_estimator import FakeRiskEstimator
from tests.unit._t20b import classify, item, make_flow
from tests.unit.test_target_guard import b3_state, clarify_state, node, seeds
from tests.unit.test_target_guard_2 import _b3_b6

SLOTS = get_slots()
P = frozenset({"LAP", "PC"})  # kỳ vọng — nguồn thật là config/slots.yaml `device_prefixes` (test dưới so)
ACC, VPN_KEYS, SOFT_KEYS = SLOTS.intents["account"].keys, SLOTS.intents["vpn"].keys, SLOTS.intents["software"].keys
REPO = Path(__file__).resolve().parents[3]

A_809 = "vpn ko vao dc bao loi 809"
B_COLLEAGUE = "Em không vào được VPN từ sáng, đồng nghiệp bên cạnh vẫn vào được bình thường"
C_TWO = "Em quên mật khẩu AD và cài giúp em 7-Zip"
C_RESET, C_7ZIP = "Em quên mật khẩu AD", "cài giúp em 7-Zip"


def _keys(intent: str) -> frozenset[str]:
    return {"account": ACC, "vpn": VPN_KEYS, "software": SOFT_KEYS}[intent]


# ---- 1. danh sách tiền tố: một nguồn trong config ---------------------------------------------------------------------------------


def test_prefixes_from_config_cover_seed() -> None:
    """`device_prefixes` (config/slots.yaml) = mọi tiền tố mã máy của seed mock (LAP, PC) — thiếu thì máy thật thành "không phải mã"."""
    seed = json.loads((REPO / "mock_services" / "seed.json").read_text(encoding="utf-8"))
    assert SLOTS.device_prefixes == P
    assert {d["device_id"].split("-")[0] for d in seed["devices"]} <= SLOTS.device_prefixes


@pytest.mark.parametrize(
    "bad",
    [pytest.param(["lap"], id="chu-thuong"), pytest.param(["NV"], id="ma-nhan-vien"), pytest.param(["SVC"], id="svc"), pytest.param(["ADM"], id="adm"), pytest.param(["LAPTOP"], id="qua-4-chu"),
     pytest.param(["L4P"], id="co-so"), pytest.param([], id="rong-ma-co-intent-may")],
)  # fmt: skip
def test_slotsfile_rejects_bad_prefixes(bad: list[str], tmp_path: Path) -> None:
    """Fail-closed lúc khởi động: tiền tố sai dáng, `NV` (mã nhân viên), hoặc rỗng khi có intent khai báo slot `device_id`."""
    raw = yaml.safe_load((get_settings().config_dir / "slots.yaml").read_text(encoding="utf-8"))
    assert SlotsFile.model_validate({**raw, "device_prefixes": ["LAP", "PC"]}).device_prefixes == P  # đối chứng: hợp lệ thì nạp được
    with pytest.raises(ValidationError):
        SlotsFile.model_validate({**raw, "device_prefixes": bad})
    bad_file = tmp_path / "slots.yaml"  # đường khởi động: `get_slots` → `load_slots`
    bad_file.write_text(yaml.safe_dump({**raw, "device_prefixes": bad}, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_slots(bad_file)


# ---- 1. hàm thuần slots.py ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "want"),
    [("lap 0610", "LAP-0610"), ("pc0977", "PC-0977"), ("Lap-0342", "LAP-0342"),
     ("loi 809", "loi 809"), ("mac0123", "mac0123"), ("MAC-0123", "MAC-0123"), ("cong 443", "cong 443")],
)  # fmt: skip
def test_canonical_only_known_prefix(raw: str, want: str) -> None:
    assert canonical_device_id(raw, P) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [(A_809, set()), ("VPN bao loi o cong 443", set()), ("may em o phong 302", set()), ("tang 3 phong 301", set()),
     ("chung chi VPN-2025-0342 het han", set()), ("vpn tren lap 0610 loi", {"LAP-0610"}), ("cai zoom len PC0977", {"PC-0977"})],
)  # fmt: skip
def test_device_ids_in_text_only_known_prefix(text: str, want: set[str]) -> None:
    assert device_ids_in_text(text, P) == want


def test_sanitize_unknown_prefix_loose_dropped_exact_kept() -> None:
    """Tiền tố lạ: dạng lỏng KHÔNG chuẩn hoá → sai mẫu → bỏ (B3 bật `dropped`, B11 hỏi); dạng chuẩn gõ đúng → giữ → B6 tra (404 → Q2)."""
    vpn = SLOTS.intents["vpn"]
    assert sanitize_slots(vpn, {"device_id": "mac 0123"}, text="VPN máy mac 0123 lỗi", device_prefixes=P) == (
        {}, {"device_id": "bad_value"})  # fmt: skip
    assert sanitize_slots(vpn, {"device_id": "MAC-0123"}, text="VPN máy MAC-0123 lỗi", device_prefixes=P) == (
        {"device_id": "MAC-0123"}, {})  # fmt: skip
    assert sanitize_slots(vpn, {"device_id": "lap 0610"}, text="VPN máy lap 0610 lỗi", device_prefixes=P) == (
        {"device_id": "LAP-0610"}, {})  # fmt: skip


# ---- target_check (hàm thuần, với tiền tố từ config) -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent", "text", "slots"),
    [
        pytest.param("vpn", A_809, {}, id="a-loi-809"),
        pytest.param("vpn", "VPN bao loi o cong 443", {}, id="a-cong-443"),
        pytest.param("vpn", "may em o phong 302 khong vao duoc VPN", {}, id="a-phong-302"),
        pytest.param("vpn", "em ngoi tang 3 phong 301, vpn khong ket noi duoc", {}, id="a-tang-3-phong-301"),
        pytest.param("software", "cai zoom giup em, bao loi 1603", {"software_name": "zoom"}, id="a-software-loi-1603"),
        pytest.param("vpn", "chứng chỉ VPN-2025-0342 hết hạn rồi", {}, id="serial-chung-chi"),
        pytest.param("vpn", B_COLLEAGUE, {}, id="b-dong-nghiep-so-sanh"),
        pytest.param("vpn", "Em khong vao duoc VPN, dong nghiep ben canh van vao duoc binh thuong", {}, id="b-khong-dau"),
        pytest.param("vpn", "giống đồng nghiệp em thì vào được, còn em thì không", {}, id="b-giong-dong-nghiep-thi-duoc"),
        pytest.param("vpn", "Em không vào được VPN, giống đồng nghiệp em thì vào được", {}, id="b-loi-DP-giong-dong-nghiep"),
        pytest.param("vpn", "Em không vào được VPN. Đồng nghiệp bên cạnh vẫn vào được bình thường.", {}, id="b-hai-cau"),
        pytest.param("vpn", "đồng nghiệp em vẫn vào được bình thường, chỉ máy em lỗi", {}, id="b-dong-nghiep-em-so-huu"),
        pytest.param("vpn", "Em không vào được VPN giống như đồng nghiệp", {}, id="b-giong-nhu"),
        pytest.param("vpn", "VPN cua em loi, so voi dong nghiep thi van vao duoc", {}, id="b-so-voi-khong-dau"),
        pytest.param("vpn", "máy em không vào VPN như các đồng nghiệp", {}, id="b-nhu-cac-dong-nghiep"),
        pytest.param("vpn", "em lỗi VPN, chị ấy vẫn bình thường", {}, id="b-chi-ay-van-binh-thuong"),
    ],
)  # fmt: skip
def test_flag_off_evidence(intent: str, text: str, slots: dict[str, str]) -> None:
    assert target_check(intent, slots, {}, _keys(intent), text, "nv001", device_prefixes=P) == (False, None)


@pytest.mark.parametrize(
    ("intent", "text", "slots", "reason"),
    [
        pytest.param("vpn", "máy của đồng nghiệp em không vào VPN", {}, "phrase", id="may-cua-dong-nghiep"),
        pytest.param("vpn", "may cua dong nghiep em khong vao VPN", {}, "phrase", id="may-cua-dong-nghiep-khong-dau"),
        pytest.param("vpn", "máy tính người khác không vào được VPN", {}, "phrase", id="may-tinh-nguoi-khac"),
        pytest.param("vpn", "máy cũ của nhân viên mới không vào được VPN", {}, "phrase", id="may-cu-cua-nhan-vien-moi"),
        pytest.param("vpn", "cấp lại chứng chỉ cho máy chị ấy", {}, "phrase", id="may-chi-ay"),
        pytest.param("software", "cài Teams cho đồng nghiệp mới vào", {"software_name": "Teams"}, "phrase", id="cho-dong-nghiep"),
        pytest.param("vpn", "VPN của đồng nghiệp bị lỗi chứng chỉ", {}, "phrase", id="vpn-cua-dong-nghiep"),
        pytest.param("software", "cài 7-Zip cho máy anh Nam", {"software_name": "7-Zip"}, "phrase", id="7zip-may-anh-Nam"),
        pytest.param("software", "Cài Zoom lên máy LAP-0610 của chị Hoa", {"software_name": "Zoom", "device_id": "LAP-0610"}, "phrase",
                     id="LAP-0610-cua-chi-Hoa"),
        pytest.param("vpn", "vpn tren lap 0610 khong vao duoc", {}, "device_text", id="lap-0610-tien-to-that"),
        pytest.param("vpn", "VPN máy MAC-0123 lỗi chứng chỉ", {}, "device_text", id="may-MAC-0123-tien-to-la"),
        pytest.param("vpn", "VPN laptop MAC-0123 lỗi chứng chỉ", {}, "device_text", id="laptop-MAC-0123"),
        pytest.param("vpn", "thiết bị MAC-0123 không vào được VPN", {}, "device_text", id="thiet-bi-MAC-0123"),
        pytest.param("software", "cài Teams cho các nhân viên mới", {"software_name": "Teams"}, "phrase", id="cho-cac-nhan-vien-moi"),
        pytest.param("software", "cài Zoom cho mấy đồng nghiệp phòng em", {"software_name": "Zoom"}, "phrase", id="cho-may-dong-nghiep"),
        pytest.param("software", "cài dùm chị ấy Zoom với", {"software_name": "Zoom"}, "phrase", id="dum-chi-ay"),
        pytest.param("vpn", "cai lai VPN giup nguoi khac trong phong", {}, "phrase", id="giup-nguoi-khac-khong-dau"),
        pytest.param("vpn", "vpn may tinh mac 0123 loi", {}, "device_text", id="may-tinh-mac-0123-khong-dau"),
        pytest.param("software", "cài Zoom lên máy của nv005", {"software_name": "Zoom"}, "identifier", id="nv005"),
        pytest.param("vpn", "chị ấy không vào được VPN", {}, "phrase", id="chu-ngu-chi-ay"),
        pytest.param("vpn", "VPN đồng nghiệp em lỗi", {}, "phrase", id="chu-ngu-vpn-dong-nghiep"),
        pytest.param("vpn", "máy anh ấy không vào mạng", {}, "phrase", id="chu-ngu-may-anh-ay"),
        pytest.param("vpn", "chi ay khong vao duoc VPN", {}, "phrase", id="chu-ngu-chi-ay-khong-dau"),
        pytest.param("vpn", "máy đồng nghiệp em vẫn chưa vào được VPN", {}, "phrase", id="van-chua-duoc-la-phu-dinh"),
        pytest.param("vpn", "đồng nghiệp em vẫn không vào được VPN", {}, "phrase", id="van-khong-duoc-la-phu-dinh"),
        pytest.param("software", "nhân viên mới bên em đều dùng Zoom, cài giúp em", {"software_name": "Zoom"}, "phrase",
                     id="nhan-vien-moi-khong-so-sanh"),
        # soát S6 (security-reviewer): miễn nhầm ở bản đầu — không phải so sánh
        pytest.param("software", "Cài Zoom cho đồng nghiệp em thì có được không ạ?", {"software_name": "Zoom"}, "phrase", id="thi-co-duoc-khong"),
        pytest.param("vpn", "Gia hạn VPN cho nhân viên mới thì mới vào được", {}, "phrase", id="thi-moi-duoc"),
        pytest.param("vpn", "Cấp VPN cho em cũng như các đồng nghiệp trong phòng", {}, "phrase", id="cung-nhu"),
        pytest.param("software", "Cài Teams cho em cũng như nhân viên mới", {"software_name": "Teams"}, "phrase", id="cung-nhu-2"),
        pytest.param("vpn", "Gia hạn VPN cho đồng nghiệp nhưng máy em vẫn dùng được", {}, "phrase", id="nhung-het-ve"),
        pytest.param("vpn", "Gia hạn VPN cho đồng nghiệp em\nmáy em vẫn vào được", {}, "phrase", id="xuong-dong-het-ve"),
        pytest.param("vpn", "Máy đồng nghiệp em vẫn kh vào được VPN", {}, "phrase", id="phu-dinh-kh"),
        pytest.param("vpn", "đồng nghiệp em vẫn có vào được đâu", {}, "phrase", id="phu-dinh-dau"),
        pytest.param("vpn", "đồng nghiệp em vẫn khum vào được VPN", {}, "phrase", id="phu-dinh-khum"),
        pytest.param("vpn", "dong nghiep em van chua vao duoc VPN", {}, "phrase", id="phu-dinh-khong-dau"),
        # soát S6 lần 2: danh sách cấm không đủ → giới từ không bao giờ miễn, từ = \w+, sau "được" chỉ nhận hết câu/dấu câu
        pytest.param("vpn", "Gia hạn VPN cho đồng nghiệp vì máy em vẫn dùng được", {}, "phrase", id="lien-tu-vi"),
        pytest.param("vpn", "Gia hạn VPN cho đồng nghiệp chứ máy em vẫn dùng được", {}, "phrase", id="lien-tu-chu"),
        pytest.param("vpn", "Cấp VPN cho nhân viên mới để họ vẫn được làm việc từ xa", {}, "phrase", id="de-van-duoc"),
        pytest.param("software", "Cài Zoom để anh ấy vẫn họp bình thường", {"software_name": "Zoom"}, "phrase", id="de-anh-ay"),
        pytest.param("vpn", "Gia hạn VPN cho nhân viên mới thì họ vào được", {}, "phrase", id="thi-dieu-kien"),
        pytest.param("software", "Cài Zoom cho đồng nghiệp em thì có được hay không?", {"software_name": "Zoom"}, "phrase", id="duoc-hay-khong"),
        pytest.param("software", "Cài Zoom cho đồng nghiệp em thì được ạ?", {"software_name": "Zoom"}, "phrase", id="duoc-a-hoi"),
        pytest.param("software", "đồng nghiệp em thì được phép không?", {"software_name": "Zoom"}, "phrase", id="duoc-phep-khong"),
        pytest.param("vpn", "Gia hạn VPN cho đồng nghiệp\u2026 máy em vẫn dùng được", {}, "phrase", id="dau-ba-cham-u2026"),
        pytest.param("vpn", "đồng nghiệp em - máy em vẫn vào được", {}, "phrase", id="gach-ngang"),
        pytest.param("vpn", "đồng nghiệp em (máy em vẫn vào được)", {}, "phrase", id="ngoac"),
        pytest.param("software", "Cài Teams cho em cũng  như nhân viên mới", {"software_name": "Teams"}, "phrase", id="cung-nhu-2-cach"),
        pytest.param("software", "Cài Teams cho mấy bạn trong phòng, chẳng hạn như nhân viên mới", {"software_name": "Teams"}, "phrase",
                     id="chang-han-nhu"),
        pytest.param("software", "Cài Teams cho cả phòng, ví dụ như nhân viên mới", {"software_name": "Teams"}, "phrase", id="vi-du-nhu"),
        pytest.param("vpn", "Đồng nghiệp em vẫn chưa vào được.", {}, "phrase", id="phu-dinh-chen-giua-het-cau"),
        pytest.param("vpn", "dong nghiep em van khong vao duoc.", {}, "phrase", id="phu-dinh-chen-giua-khong-dau"),
        pytest.param("vpn", "VPN đồng nghiệp lỗi mà em vẫn vào được", {}, "phrase", id="lien-tu-ma-het-ve"),
        # soát S6 lần 3: từ chen TRƯỚC "vẫn/thì" (phủ định, lỗi/nhu cầu, đổi chủ ngữ), nhượng bộ "dù", `$` trước "\n"
        pytest.param("vpn", "Đồng nghiệp không vào được VPN em vẫn vào được", {}, "phrase", id="truoc-van-phu-dinh-doi-chu-ngu"),
        pytest.param("vpn", "Chị ấy bị lỗi VPN em vẫn bình thường", {}, "phrase", id="truoc-van-bi-loi"),
        pytest.param("vpn", "Nhân viên mới chưa có VPN em thì được", {}, "phrase", id="truoc-thi-chua-co"),
        pytest.param("software", "Đồng nghiệp cần cài Zoom em thì được", {"software_name": "Zoom"}, "phrase", id="truoc-thi-can"),
        pytest.param("vpn", "dong nghiep khong vao duoc VPN em van vao duoc", {}, "phrase", id="truoc-van-khong-dau"),
        pytest.param("vpn", "Đồng nghiệp em vẫn lỗi dù vào được, nhờ IT xem giúp", {}, "phrase", id="nhuong-bo-du"),
        pytest.param("vpn", "Chị ấy vẫn lỗi mặc dù vào được", {}, "phrase", id="nhuong-bo-mac-du"),
        pytest.param("vpn", "Chị ấy vẫn lỗi tuy vào được", {}, "phrase", id="nhuong-bo-tuy"),
        pytest.param("vpn", "em lỗi VPN như \nđồng nghiệp", {}, "phrase", id="xuong-dong-sau-nhu"),
        # ca TÁCH từng lớp (mutation M11a, M11e, M12b, M12d — các lớp chồng nhau nên ca trên không tách được)
        pytest.param("vpn", "Đồng nghiệp\u2026 máy vẫn vào được", {}, "phrase", id="tach-ky-tu-u2026"),
        pytest.param("vpn", "Đồng nghiệp nghỉ phép nên máy vẫn dùng được", {}, "phrase", id="tach-lien-tu-nen"),
        pytest.param("vpn", "Chị ấy dù vẫn vào được.", {}, "phrase", id="tach-nhuong-bo-du"),
        pytest.param("vpn", "Nhân viên mới cần VPN thì được.", {}, "phrase", id="tach-nhu-cau-can"),
        # soát S6 lần 4: "như" liệt kê sau yêu cầu cho người khác
        pytest.param("software", "Cài Teams cho cả phòng, như nhân viên mới", {"software_name": "Teams"}, "phrase", id="nhu-liet-ke-ca-phong"),
        pytest.param("software", "Cài Zoom cho các bạn như nhân viên mới", {"software_name": "Zoom"}, "phrase", id="nhu-liet-ke-cac-ban"),
        pytest.param("vpn", "Cấp VPN cho mọi người, như đồng nghiệp ngồi cạnh", {}, "phrase", id="nhu-liet-ke-moi-nguoi"),
        pytest.param("vpn", "Gia hạn VPN, như đồng nghiệp em", {}, "phrase", id="nhu-sau-dong-tu-yeu-cau"),
        pytest.param("vpn", "Em không vào được VPN, cũng như đồng nghiệp", {}, "phrase", id="tach-cung-nhu-khong-yeu-cau"),
    ],
)  # fmt: skip
def test_flag_still_on(intent: str, text: str, slots: dict[str, str], reason: str) -> None:
    mention, got = target_check(intent, slots, {}, _keys(intent), text, "nv001", device_prefixes=P)
    assert got == reason
    assert mention is (reason in ("identifier", "phrase"))


def test_unknown_prefix_without_cue_is_residual() -> None:
    """PHẦN CÒN LẠI (ĐP chốt 3): tiền tố lạ KHÔNG đứng ngay sau máy/laptop/pc/thiết bị → không coi là mã máy → không cờ."""
    assert target_check("vpn", {}, {}, VPN_KEYS, "MAC-0123 không vào được VPN", "nv001", device_prefixes=P) == (False, None)


@pytest.mark.parametrize("intent", ["account", "access"])
@pytest.mark.parametrize("phrase", ["đồng nghiệp bên cạnh", "người khác", "nhân viên mới", "anh ấy", "dong nghiep ben canh"])
def test_account_access_generic_phrase_alone_still_flags(intent: str, phrase: str) -> None:
    """Cụm chung đứng một mình (không "máy", không giới từ) — account/access VẪN bật như be-target-guard."""
    keys = SLOTS.intents[intent].keys
    assert target_check(intent, {}, {}, keys, f"{phrase} cần làm việc này gấp", "nv001", device_prefixes=P) == (True, "phrase")


def test_account_access_phrases_unchanged() -> None:
    """Đề xuất 2 chỉ áp vpn/software: account/access vẫn bật với cụm chung đứng một mình (như be-target-guard)."""
    assert target_check("account", {"account_type": "ad"}, {}, ACC, "đồng nghiệp bên cạnh quên mật khẩu AD", "nv001",
                        device_prefixes=P) == (True, "phrase")  # fmt: skip
    assert target_check("account", {"account_type": "ad"}, {}, ACC, "chị ấy quên mật khẩu", "nv001", device_prefixes=P) == (
        True, "phrase")  # fmt: skip


def test_identifier_machine_exclusion_uses_prefix_list() -> None:
    """Loại trừ mã máy trong `identifier` (account/access) cũng theo danh sách: LAP-0342 vẫn không tính; `kt-0012` (không phải tiền tố
    máy) giờ TÍNH là định danh lạ — chỉ CHẶT hơn (trước đây dáng `[a-z]{2,4}-\\d{3,5}` bị coi là mã máy → lọt)."""
    assert target_check("account", {"account_type": "ad"}, {}, ACC, "mở khoá tài khoản AD, máy LAP-0342", "nv001",
                        device_prefixes=P) == (False, None)  # fmt: skip
    assert target_check("account", {"account_type": "ad"}, {}, ACC, "mở khoá tài khoản kt-0012 giúp", "nv001", device_prefixes=P) == (
        True, "identifier")  # fmt: skip


# ---- 3. nhiều ý: bỏ qua slot tài nguyên của MỌI ý chạy được ---------------------------------------------------------------------


def test_multi_sibling_resource_slot_ignored() -> None:
    slots = {"account_type": "ad", "action": "reset_password"}
    assert target_check("account", slots, {}, ACC, C_TWO, "nv001", device_prefixes=P) == (True, "identifier")  # đối chứng: lỗi (c)
    assert target_check("account", slots, {}, ACC, C_TWO, "nv001", device_prefixes=P, sibling_slots=[{"software_name": "7-Zip"}]) == (
        False, None)  # fmt: skip


def test_multi_other_identifier_still_flags() -> None:
    text = "đặt lại mật khẩu cho nv005 và cài 7-Zip"
    got = target_check("account", {"account_type": "ad"}, {}, ACC, text, "nv001", device_prefixes=P,
                       sibling_slots=[{"software_name": "7-Zip"}])  # fmt: skip
    assert got == (True, "identifier")


def test_multi_sibling_never_ignores_employee_id_or_non_resource_slot() -> None:
    """Ý bên cạnh bị LLM điền `software_name = "nv005"` (có trong câu, qua mẫu) KHÔNG được che mã nhân viên; slot không phải tài nguyên
    (`target_user`) của ý bên cạnh không vào tập bỏ qua."""
    text = "đặt lại mật khẩu cho nv005 và cài nv005"
    got = target_check("account", {"account_type": "ad"}, {}, ACC, text, "nv001", device_prefixes=P,
                       sibling_slots=[{"software_name": "nv005"}])  # fmt: skip
    assert got == (True, "identifier")
    text = "gia hạn quyền thư mục public-reports cho hoa.bt và cài 7-Zip"
    got = target_check("access", {"action": "extend_permission", "resource_path": "public-reports"}, {}, SLOTS.intents["access"].keys,
                       text, "nv001", device_prefixes=P, sibling_slots=[{"software_name": "7-Zip", "target_user": "hoa.bt"}])  # fmt: skip
    assert got == (True, "identifier")


@pytest.mark.parametrize(
    ("text", "sibling"),
    [pytest.param("đặt lại mật khẩu cho NV005 và cài NV005", {"software_name": "NV005"}, id="NV005-hoa"),
     pytest.param("mở khoá svc_backup và cho em quyền đọc thư mục svc_backup", {"resource_path": "svc_backup"}, id="svc_backup-resource"),
     pytest.param("mở khoá it_mgr01 và cài it_mgr01", {"software_name": "it_mgr01"}, id="it_mgr01-software"),
     pytest.param("mở khoá cho hoa.bt và cài hoa.bt", {"software_name": "hoa.bt"}, id="hoa.bt-xuat-hien-trong-y-account"),
     pytest.param("mở khoá tài khoản AD giúp em và cấp quyền đọc thư mục svc_backup", {"resource_path": "svc_backup"},
                  id="svc_backup-chi-o-y-ben-canh")],
)  # fmt: skip
def test_multi_sibling_cannot_mask_user_like_identifier(text: str, sibling: dict[str, str]) -> None:
    """Soát bảo mật PLAN (mục 2): ý bên cạnh bị LLM điền giá trị dáng mã người dùng (`^[a-z0-9_]{3,64}$` có số hoặc `_`, sau casefold)
    không được bỏ qua; `hoa.bt` không dáng đó nhưng cũng nằm trong SPAN của chính ý account (tham số `own_span`) → không bỏ qua."""
    span = text.split(" và ")[0]
    got = target_check("account", {"action": "unlock_account"}, {}, ACC, text, "nv001", device_prefixes=P,
                       sibling_slots=[sibling], own_span=span)  # fmt: skip
    assert got == (True, "identifier")


def test_call_sites_always_pass_prefixes() -> None:
    """Soát bảo mật PLAN (mục 4): mọi lời gọi `target_check` / `sanitize_slots` trong `backend/app` truyền `device_prefixes=` (mặc định
    `None` = dáng cũ chỉ để test cũ gọi trần)."""
    import ast

    calls = 0
    for path in (REPO / "backend" / "app").rglob("*.py"):
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)  # gọi trần và dạng `module.fn(...)`
            if name in ("target_check", "sanitize_slots", "mention_reason"):
                calls += 1
                assert any(k.arg == "device_prefixes" for k in n.keywords), f"{path.name}:{n.lineno}"
    assert calls >= 9  # B3 một ý (2), B5 _seed (2) + _split (1), clarify_wait (2), target.py mention_reason (2)


# ---- node B3 một ý → B6 (call site truyền tiền tố) ---------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [A_809, "VPN bao loi o cong 443", "may em o phong 302 khong vao duoc VPN", "em ngoi tang 3 phong 301, vpn khong ket noi duoc",
     B_COLLEAGUE],
)  # fmt: skip
async def test_b3_b6_evidence_no_flag_infers_own_device(text: str) -> None:
    """(a), (b): không cờ → B6 tự suy máy duy nhất LAP-0342 của nv001 (đường Q2 mở lại)."""
    st = await _b3_b6("vpn", text, {}, "renew_vpn_cert")
    assert not (st.get("ctx_flags") or {}).get("target_is_other")
    assert st["slots"]["device_id"] == "LAP-0342"
    assert st["facts"]["device_owner_is_requester"] is True


@pytest.mark.asyncio
async def test_b3_b6_known_prefix_other_device_still_flags() -> None:
    """Dương ở call site B3 một ý: "lap 0610" (LLM bỏ khoá máy) vẫn bật `device_text` → B6 không suy LAP-0342."""
    st = await _b3_b6("vpn", "vpn tren lap 0610 khong vao duoc", {}, "renew_vpn_cert")
    assert st["ctx_flags"] == {"target_is_other": True}
    assert "device_id" not in st["slots"]


# ---- node B5 (nhiều ý) -------------------------------------------------------------------------------------------------------


def _reset(span: str) -> dict[str, Any]:
    return item("account", span, action="reset_password", slots={"account_type": "ad"})


def _7zip(span: str, **kw: Any) -> dict[str, Any]:
    return item("software", span, action="install_software", slots={"software_name": "7-Zip"}, **kw)


@pytest.mark.asyncio
async def test_b5_c_account_child_not_flagged_never_asks_whose_account() -> None:
    """(c): con account không bật cờ (7-Zip là slot tài nguyên của con software) → không hỏi "tài khoản của ai?"."""
    f = make_flow(classify(_reset(C_RESET), _7zip(C_7ZIP)))
    await f.submit(C_TWO)
    s = await seeds(f)
    assert "ctx_flags" not in s["T1-1"] and "ctx_flags" not in s["T1-2"]
    [split] = [r for r in f.h.audit.rows if r["ticket_id"] == "T1" and r["event"] == "split_into_2_children"]
    assert split["detail"]["children_other_target_reason"] == [None, None]
    for t in ("T1", "T1-1"):
        assert all(TARGET_QUESTION not in str(m.get("text") or m.get("content") or "") for m in await f.assistant_msgs(t))


@pytest.mark.asyncio
async def test_b5_other_employee_id_still_flags_account_child() -> None:
    reset, zoom = "đặt lại mật khẩu cho nv005", "cài 7-Zip"
    f = make_flow(classify(_reset(reset), _7zip(zoom)))
    await f.submit(f"{reset} và {zoom}")
    s = await seeds(f)
    assert s["T1-1"]["ctx_flags"] == {"target_is_other": True}
    [split] = [r for r in f.h.audit.rows if r["ticket_id"] == "T1" and r["event"] == "split_into_2_children"]
    assert split["detail"]["children_other_target_reason"][0] == "identifier"


@pytest.mark.asyncio
async def test_b5_non_runnable_sibling_slots_not_ignored() -> None:
    """Ý bên cạnh KHÔNG chạy được (confidence thấp → E1) không đóng góp slot → con account vẫn bật (thận trọng)."""
    f = make_flow(classify(_reset(C_RESET), _7zip(C_7ZIP, confidence=0.1)))
    await f.submit(C_TWO)
    s = await seeds(f)
    assert s["T1-1"]["ctx_flags"] == {"target_is_other": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(("vpn_span", "flag"), [("vpn ko vao dc bao loi 809", False), ("vpn tren lap 0610 ko vao dc", True)])
async def test_b5_vpn_child_uses_prefixes(vpn_span: str, flag: bool) -> None:
    """Call site B5 `_seed`: con vpn "loi 809" không cờ; "lap 0610" vẫn cờ."""
    reset = "đặt lại mật khẩu AD cho em"
    f = make_flow(classify(_reset(reset), item("vpn", vpn_span, action="renew_vpn_cert")))
    await f.submit(f"{reset}, {vpn_span}")
    s = await seeds(f)
    assert (s["T1-2"].get("ctx_flags") == {"target_is_other": True}) is flag


# ---- clarify_wait (call site truyền tiền tố) ------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "flag"),
    [("may em bao loi 809", False), ("em o phong 302", False), ("may lap 0610 a", True), ("máy của đồng nghiệp em", True)],
)  # fmt: skip
async def test_clarify_vpn_reply(monkeypatch: pytest.MonkeyPatch, reply: str, flag: bool) -> None:
    n = node({"b11_extract_slots": lambda _: Reply({"slots": {}, "off_topic": False})})
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": reply})
    out = await n.run("clarify_wait", clarify_wait, clarify_state(["device_id"], {"action": "renew_vpn_cert"}, intent="vpn"))
    assert out["status"] == S_CLARIFYING
    assert ((out.get("ctx_flags") or {}).get("target_is_other") is True) is flag


# ---- lưới cuối: cờ không bật mà đích là máy người khác → vẫn chặn ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "text", "slots", "action"),
    [("software", "Cài Zoom lên máy LAP-0610", {"software_name": "Zoom", "device_id": "LAP-0610"}, "install_software"),
     ("vpn", "Cấp lại chứng chỉ VPN cho máy LAP-0610", {"device_id": "LAP-0610"}, "renew_vpn_cert")],
)  # fmt: skip
async def test_net_other_device_no_flag_no_allow_rule_no_exec(intent: str, text: str, slots: dict[str, str], action: str) -> None:
    """Mã máy NGƯỜI KHÁC có trong slot, câu không cụm → KHÔNG cờ. Lưới: fact chủ máy (tool) False → `build_ctx.target_is_other` → không
    luật allow nào khớp (R11/R16/R20 đòi False) → không tự làm; 0 phiếu, 0 lần thực hiện. (`make_flow` tắt lớp LLM của B12 → E5
    `llm_layer_disabled`; nhánh có lớp LLM → B15 P6: test dưới.)"""
    f = make_flow(classify(item(intent, text, action=action, slots=slots)))
    r = await f.submit(text)
    v = await f.values("T1")
    assert not (v.get("ctx_flags") or {}).get("target_is_other")
    assert Action.model_validate(v["intended_action"]).facts["device_owner_is_requester"] is False
    assert RiskDecision.model_validate(v["risk"]).matched_rule_id is None
    assert (r.status, v["exit_code"]) == (S_ESCALATED, "E5")
    assert f.h.approvals.count("T1") == 0 and f.h.executor.calls["T1"] == 0


@pytest.mark.asyncio
async def test_net_nodes_no_flag_other_device_llm_hitl_then_b15_p6_e5() -> None:
    """Như demo (lớp AI chạy, ước lượng thấp, chưa hiệu chỉnh → HITL), KHÔNG cờ: B15 chốt P6 → E5 `approval_target_unverified`, 0 phiếu."""
    text = "Cài Zoom lên máy LAP-0610"
    it = item("software", text, action="install_software", slots={"software_name": "Zoom", "device_id": "LAP-0610"})
    n = node({"b03_classify": lambda _: Reply({"intents": [it], "is_multi": False})})
    state = b3_state(text)
    for name, module, expect in (("b03_classify", b03_classify, S_DIAGNOSING), ("b06_diagnose", b06_diagnose, S_RETRIEVING),
                                 ("b11_slots", b11_slots, S_ASSESSING)):  # fmt: skip
        state = await n.run(name, module, state)
        assert state["status"] == expect, (name, state.get("exit_code"), state.get("escalation_reason_detail"))
    assert not (state.get("ctx_flags") or {}).get("target_is_other")
    chunk = ChunkRef(chunk_id="KB#0", doc_id="KB-SW-001", version=1, seq=0, title="T", heading_path="H", score=0.95, excerpt="x")
    state = {**state, "retrieved": [chunk], "retrieval_score": 0.95, "kb_version": "a" * 64}
    est = FakeRiskEstimator(RiskEstimate(raw_prob=0.01, p_method="self_report", factors=(FactorCode.ROUTINE_LOW_RISK,),
                                         prompt_id="b14_risk_estimate", prompt_version="1", model="gia", evidence_trimmed=0))  # fmt: skip
    state = await n.run("b12_assess", b12_assess, state, estimator=est, calibrator=None)
    risk = RiskDecision.model_validate(state["risk"])
    assert (risk.matched_rule_id, risk.route) == (None, "HITL")
    state = await n.run("b15_prepare_approval", b15_prepare_approval, state)
    assert (state["exit_code"], state["escalation_reason_detail"]) == ("E5", "approval_target_unverified")
    assert n.row("B15")["detail"]["stage"] == "target_guard"
    assert n.h.approvals.count("t1") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["chị ấy không vào được VPN", "VPN đồng nghiệp em lỗi", "máy anh ấy không vào mạng"])
async def test_b3_b6_generic_subject_flags_no_infer(text: str) -> None:
    """ĐP chốt 2: cụm chung làm chủ ngữ VẪN bật cờ → B6 không tự suy LAP-0342 của người gửi (B11 hỏi mã máy)."""
    st = await _b3_b6("vpn", text, {}, "renew_vpn_cert")
    assert st["ctx_flags"] == {"target_is_other": True}
    assert "device_id" not in st["slots"] and "device_owner_is_requester" not in st["facts"]
