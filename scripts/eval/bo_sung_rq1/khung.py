"""Đo bổ sung RQ1 (16/11/2026) — bước 1: dựng KHUNG tình huống cho người viết thẻ. Chỉ đọc repo, không mạng, không stack.

  uv run python scripts/eval/bo_sung_rq1/khung.py --out <thư mục MỚI ngoài repo>

Chạy trên nhánh `do-bo-sung-rq1` (tách từ tag `v1.0-freeze` = bf94df2) để luật (`config/policy.json`, 20 luật) và dữ liệu giả lập
(`mock_services/seed.json`) đúng bản đo. Quy trình ghi trước ở `eval/bo-sung-rq1/GHI-TRUOC.md`:

1. Liệt kê MỌI tổ hợp (người gửi, hành động, đối tượng, người được làm hộ) dựng được từ seed, dữ kiện suy từ seed.
2. Giữ tổ hợp KHÔNG luật nào khớp — chấm bằng chính `scripts/rule_coverage.py` (`evaluate_scenario`), cùng cách đếm 66 thẻ lớp LLM của bộ cũ.
3. Bỏ tổ hợp đã có trong `eval/the100` (cùng người gửi + hành động + đối tượng + người được làm hộ) và tổ hợp làm harness lỗi đăng nhập
   (người gửi có OTP hoặc gây xung đột người duyệt → Trưởng BP có OTP).
4. Chia 4 nhóm (A–D, `NHOM`) theo quan hệ người gửi ↔ người bị tác động; trong mỗi nhóm chia theo loại hành động; rút ngẫu nhiên có hạt
   giống cố định `HAT_GIONG` đúng số `CHI_TIEU`, rồi rút thêm `DU_PHONG` thẻ dự phòng mỗi nhóm (dùng khi người viết đánh dấu "không tự nhiên").

Không có nhãn ở bước này: nhãn do hai người gán mù sau khi thẻ viết xong (`dung_the.py phieu-gan`).

Đầu ra (`--out` phải chưa tồn tại): `khung.csv` (mọi cột, cho script), `phieu-viet.xlsx` (cho người viết: mô tả + ô viết câu),
`ung-vien.csv` (toàn bộ tổ hợp đi lớp LLM và nhóm của nó — để soát cách rút).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))  # rule_coverage tự thêm backend/ vào sys.path

import rule_coverage as rc

HAT_GIONG = 20261116
AT_MAC_DINH = "2026-11-18T10:00:00+07:00"  # thứ Tư, trong giờ hành chính (T2–T6 08:00–18:00) — GHI-TRUOC mục 4
# Người gửi bị loại: it_mgr01 có OTP (harness lỗi 401); l1_01 là người duyệt chính, l1_lead nằm trong chuỗi quản lý của l1_01 → phiếu
# chuyển Trưởng BP it_mgr01 (OTP) → lỗi 401 ở bước duyệt (Bảng L.19 của báo cáo: HB07-q1/q2, HB16).
NGUOI_GUI_LOAI = frozenset({"it_mgr01", "l1_01", "l1_lead"})
DOI_TUONG_LOAI = frozenset(
    {"l1_01", "svc_backup"}
)  # l1_01: xung đột người duyệt; svc_backup: tài khoản dịch vụ (luật R03)
IT_STAFF = frozenset({"l1_02", "l2_01"})
TRUONG_PHONG = frozenset({"fin_head", "eng_head", "sales_head", "hr_head"})

# Chỉ tiêu mỗi nhóm × loại việc (GHI-TRUOC mục 3). Loại việc: account = đặt lại mật khẩu / mở khoá; access = xem/cấp/gia hạn quyền;
# vpn = gia hạn / cấp lại VPN; software = cài phần mềm.
CHI_TIEU: Mapping[str, Mapping[str, int]] = {
    "A": {
        "account": 6,
        "access": 5,
        "vpn": 3,
        "software": 3,
    },  # IT làm hộ người ngoài IT — 17
    "B": {
        "account": 2,
        "access": 4,
        "vpn": 3,
        "software": 2,
    },  # Trưởng phòng làm hộ người cùng phòng — 11 (B/account chỉ có 2 người khác nhau)
    "C": {
        "account": 5,
        "access": 3,
        "vpn": 2,
        "software": 2,
    },  # nhân viên nhờ cho đồng nghiệp cùng phòng / cấp trên — 12
    "D": {
        "account": 2,
        "access": 2,
    },  # tự làm cho mình mà không luật nào khớp — 4 (cả nhóm chỉ có 4 tổ hợp)
}
DU_PHONG = 3
NHOM = {
    "A": "Nhân viên IT (L1/L2) làm hộ người ngoài phòng IT",
    "B": "Trưởng phòng làm hộ người cùng phòng",
    "C": "Nhân viên nhờ làm cho đồng nghiệp cùng phòng hoặc cấp trên",
    "D": "Tự làm cho chính mình (không luật nào khớp)",
}
LOAI = {
    "reset_password": "account",
    "unlock_account": "account",
    "view_permissions": "access",
    "grant_permission": "access",
    "extend_permission": "access",
    "install_software": "software",
    "renew_vpn_cert": "vpn",
    "reissue_vpn_access": "vpn",
}
INTENT = {
    "account": "account",
    "access": "access",
    "vpn": "vpn",
    "software": "software",
}
TAI_KHOAN = {
    "ad": "tài khoản đăng nhập máy (AD)",
    "email": "email công ty",
    "erp": "tài khoản ERP",
}
LY_DO_KHOA = {
    "bad_password": "nhập sai mật khẩu nhiều lần",
    "admin": "quản trị viên khoá",
    "inactivity": "lâu không dùng",
    "other": "lý do khác",
}
TRANG_THAI = {
    "active": "đang làm việc",
    "probation": "đang thử việc",
    "disabled": "đang bị vô hiệu hoá",
    "terminated": "đã nghỉ việc",
}
MUC_QUYEN = {"read": "chỉ đọc", "write": "đọc và ghi", "full": "toàn quyền"}
THU_TU_QUYEN = {"read": 1, "write": 2, "full": 3}
SO_NGAY = 30


@dataclass
class UngVien:
    """Một tổ hợp. `khoa` = (người gửi, hành động, đối tượng, người được làm hộ) — đơn vị loại trùng với bộ cũ."""

    nguoi_gui: str
    hanh_dong: str
    doi_tuong: str
    lam_ho: str
    tham_so: dict[str, Any]
    du_kien: dict[str, Any]
    nhom: str = ""
    quyet_dinh: str = ""
    mo_ta: str = ""
    du_kien_chu: str = ""
    canh_bao: list[str] = field(default_factory=list)

    @property
    def loai(self) -> str:
        return LOAI[self.hanh_dong]

    @property
    def khoa(self) -> tuple[str, str, str, str]:
        return (self.nguoi_gui, self.hanh_dong, self.doi_tuong, self.lam_ho)


# ---- seed -----------------------------------------------------------------------------------------------------------


class SeedGoc:
    """Đọc seed thô (như `rule_coverage.Seed`) + các bảng rule_coverage không cần (chứng chỉ, quyền hiện có, phần mềm đã cài)."""

    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.users: dict[str, dict[str, Any]] = {u["user_id"]: u for u in raw["users"]}
        self.devices: dict[str, dict[str, Any]] = {
            d["device_id"]: d for d in raw["devices"]
        }
        self.certs: dict[str, dict[str, Any]] = {
            c["device_id"]: c for c in raw["certs"]
        }
        self.resources: dict[str, dict[str, Any]] = {
            r["path"]: r for r in raw["resources"]
        }
        self.catalog: dict[str, dict[str, Any]] = {c["name"]: c for c in raw["catalog"]}
        self.perms: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for p in raw["permissions"]:
            self.perms[p["user_id"]][p["path"]] = p
        self.installed: dict[str, set[str]] = defaultdict(set)
        for i in raw["installed"]:
            self.installed[i["device_id"]].add(i["name"])

    def ten(self, uid: str) -> str:
        u = self.users[uid]
        return f"{u['full_name']} ({uid}, {u['title']}, phòng {u['department']})"

    def dang_nhap_duoc(self, uid: str) -> bool:
        u = self.users[uid]
        return u["employment_status"] in ("active", "probation") and not u.get(
            "is_service_account"
        )


def du_kien_tai_khoan(s: SeedGoc, uid: str, acct: str) -> dict[str, Any]:
    u, a = s.users[uid], s.users[uid]["accounts"][acct]
    f: dict[str, Any] = {"target_account_privilege": a.get("privilege", "standard_user"),
                         "target_is_service_account": bool(u.get("is_service_account")),
                         "target_user_status": u["employment_status"], "target_account_locked": bool(a.get("locked", False))}  # fmt: skip
    if a.get("locked"):
        f["target_lock_reason"] = (
            a.get("lock_reason") if a.get("lock_reason") in LY_DO_KHOA else "other"
        )
    if u.get("disable_reason"):
        f["target_disable_reason"] = u["disable_reason"]
    return f


def du_kien_may(s: SeedGoc, nguoi_gui: str, dev: str) -> dict[str, Any]:
    d = s.devices[dev]
    cua_nguoi_gui = [x for x in s.devices.values() if x["owner_id"] == nguoi_gui]
    f: dict[str, Any] = {"device_count": len(cua_nguoi_gui), "has_registered_device": any(x["registered"] for x in cua_nguoi_gui),
                         "device_registered": bool(d["registered"]), "device_owner_is_requester": d["owner_id"] == nguoi_gui}  # fmt: skip
    c = s.certs.get(dev)
    if c is None:
        f["cert_status"] = "none"
    else:
        f["cert_status"] = (
            "revoked"
            if c.get("revoked")
            else ("expired" if c["expires_in_days"] < 0 else "valid")
        )
        f["cert_days_to_expiry"] = int(c["expires_in_days"])
    return f


def liet_ke(s: SeedGoc) -> Iterator[UngVien]:
    """Mọi tổ hợp dựng được — chưa lọc luật. Người gửi: đăng nhập được, không ở `NGUOI_GUI_LOAI`."""
    gui = sorted(u for u in s.users if s.dang_nhap_duoc(u) and u not in NGUOI_GUI_LOAI)
    dich = sorted(u for u in s.users if u not in DOI_TUONG_LOAI)
    for r in gui:
        for t in dich:
            for acct in sorted(s.users[t]["accounts"]):
                f = du_kien_tai_khoan(s, t, acct)
                yield UngVien(
                    r, "reset_password", f"user:{t}", t, {"account_type": acct}, dict(f)
                )
                if f["target_account_locked"]:
                    yield UngVien(
                        r,
                        "unlock_account",
                        f"user:{t}",
                        t,
                        {"account_type": acct},
                        dict(f),
                    )
            if t != r:
                yield UngVien(
                    r,
                    "view_permissions",
                    f"user:{t}",
                    t,
                    {},
                    {"target_user_status": s.users[t]["employment_status"]},
                )
            for path, res in sorted(s.resources.items()):
                rec = s.perms[t].get(path)
                base: dict[str, Any] = {"resource_sensitivity": res["sensitivity"],
                                        "same_department": res["owner_department"] == s.users[t]["department"],
                                        "target_user_status": s.users[t]["employment_status"], "has_permission_record": rec is not None}  # fmt: skip
                if s.users[t].get("disable_reason"):
                    base["target_disable_reason"] = s.users[t]["disable_reason"]
                if rec is not None:
                    base["existing_permission_level"] = rec["level"]
                het_han = (
                    rec is not None
                    and rec["expires_in_days"] is not None
                    and rec["expires_in_days"] < 0
                )
                for lvl in (
                    "read",
                    "write",
                ):  # chỉ xin quyền mới, quyền cao hơn, hoặc cấp lại khi quyền cũ đã hết hạn
                    if (
                        rec is None
                        or het_han
                        or THU_TU_QUYEN[lvl] > THU_TU_QUYEN[rec["level"]]
                    ):
                        yield UngVien(
                            r,
                            "grant_permission",
                            f"folder:{path}",
                            t,
                            {"permission_level": lvl, "duration_days": SO_NGAY},
                            dict(base),
                        )
                if rec is not None:
                    yield UngVien(
                        r,
                        "extend_permission",
                        f"folder:{path}",
                        t,
                        {"duration_days": SO_NGAY},
                        dict(base),
                    )
        for dev in sorted(s.devices):
            f = du_kien_may(s, r, dev)
            if f["cert_status"] != "none":
                for typ in ("renew_vpn_cert", "reissue_vpn_access"):
                    yield UngVien(r, typ, f"device:{dev}", r, {}, dict(f))
            for sw, c in sorted(s.catalog.items()):
                if sw in s.installed[dev]:
                    continue
                sf = {"device_owner_is_requester": f["device_owner_is_requester"], "device_registered": f["device_registered"],
                      "in_catalog": True, "license_paid": c["license_type"] == "paid",
                      "requires_local_admin": bool(c["requires_local_admin"])}  # fmt: skip
                yield UngVien(
                    r,
                    "install_software",
                    f"device:{dev}",
                    r,
                    {"device_id": dev, "software_name": sw},
                    sf,
                )


# ---- nhóm + mô tả -----------------------------------------------------------------------------------------------------


def chu_dich(s: SeedGoc, uv: UngVien) -> str:
    """Người bị tác động: account/access → người được làm hộ; vpn/software → chủ máy."""
    if uv.loai in ("vpn", "software"):
        return str(s.devices[uv.doi_tuong.split(":", 1)[1]]["owner_id"])
    return uv.lam_ho


def xep_nhom(s: SeedGoc, uv: UngVien) -> str:
    """A–D (GHI-TRUOC mục 3) hoặc "" = không dùng (quan hệ không tự nhiên theo quy tắc ghi trước: IT làm hộ người trong IT, người ngoài
    IT làm hộ người khác phòng mà không phải cấp trên trực tiếp)."""
    r, t = uv.nguoi_gui, chu_dich(s, uv)
    if r == t:
        return "D"
    if r in IT_STAFF:
        return "A" if s.users[t]["department"] != "IT" else ""
    cung_phong = s.users[t]["department"] == s.users[r]["department"]
    if r in TRUONG_PHONG and cung_phong:
        return "B"
    if cung_phong or s.users[r].get("manager_id") == t:
        return "C"
    return ""


def mo_ta(s: SeedGoc, uv: UngVien) -> tuple[str, str]:
    """(việc cần nhờ, dữ kiện bằng chữ) — tiếng Việt, cho người viết và người gán."""
    f, p = uv.du_kien, uv.tham_so
    _, _, ref = uv.doi_tuong.partition(":")
    nguoi = (
        "chính mình"
        if uv.lam_ho == uv.nguoi_gui and uv.loai in ("account", "access")
        else s.ten(uv.lam_ho)
    )
    dk: list[str] = []
    if uv.hanh_dong in ("reset_password", "unlock_account"):
        viec = (
            "Đặt lại mật khẩu" if uv.hanh_dong == "reset_password" else "Mở khoá"
        ) + f" {TAI_KHOAN[p['account_type']]} của {nguoi}"
        dk.append(
            f"Tài khoản: quyền {f['target_account_privilege']}, chủ tài khoản {TRANG_THAI[f['target_user_status']]}"
        )
        dk.append(
            f"Đang bị khoá ({LY_DO_KHOA[f['target_lock_reason']]})"
            if f["target_account_locked"]
            else "Tài khoản không bị khoá"
        )
    elif uv.hanh_dong == "view_permissions":
        viec = f"Xem {nguoi} đang có quyền vào những thư mục nào"
        dk.append(f"Người được xem: {TRANG_THAI[f['target_user_status']]}")
    elif uv.hanh_dong in ("grant_permission", "extend_permission"):
        res = s.resources[ref]
        if uv.hanh_dong == "grant_permission":
            viec = f"Cấp quyền {MUC_QUYEN[p['permission_level']]} thư mục {ref} trong {SO_NGAY} ngày cho {nguoi}"
        else:
            viec = (
                f"Gia hạn thêm {SO_NGAY} ngày quyền đang có ở thư mục {ref} cho {nguoi}"
            )
        dk.append(
            f"Thư mục {ref}: độ nhạy {res['sensitivity']}, thuộc phòng {res['owner_department']}"
        )
        rec = s.perms[uv.lam_ho].get(ref)
        if rec is None:
            dk.append("Người được cấp chưa có quyền nào ở thư mục này")
        else:
            han = rec["expires_in_days"]
            con = (
                "không thời hạn"
                if han is None
                else (f"còn {han} ngày" if han >= 0 else f"đã hết hạn {-han} ngày")
            )
            dk.append(f"Đang có quyền {MUC_QUYEN[rec['level']]}, {con}")
        dk.append(f"Người được cấp: {TRANG_THAI[f['target_user_status']]}")
    else:
        dev = s.devices[ref]
        chu = (
            "của chính người gửi"
            if dev["owner_id"] == uv.nguoi_gui
            else f"của {s.ten(dev['owner_id'])}"
        )
        if uv.loai == "software":
            c = s.catalog[p["software_name"]]
            viec = f"Cài {c['display_name']} lên máy {ref} ({chu})"
            dk.append(
                f"Phần mềm trong danh mục công ty, {'có phí' if c['license_type'] == 'paid' else 'miễn phí'}"
            )
        else:
            viec = (
                "Gia hạn chứng chỉ VPN"
                if uv.hanh_dong == "renew_vpn_cert"
                else "Cấp lại quyền truy cập VPN"
            ) + f" cho máy {ref} ({chu})"
            if f["cert_status"] == "revoked":
                dk.append("Chứng chỉ VPN của máy đã bị thu hồi")
            elif f["cert_days_to_expiry"] < 0:
                dk.append(
                    f"Chứng chỉ VPN hết hạn {-f['cert_days_to_expiry']} ngày trước"
                )
            else:
                dk.append(f"Chứng chỉ VPN còn {f['cert_days_to_expiry']} ngày")
        dk.append(
            f"Máy {dev['kind']}, {'đã' if dev['registered'] else 'CHƯA'} đăng ký với IT"
        )
    return viec, "; ".join(dk)


# ---- chấm luật bằng rule_coverage ---------------------------------------------------------------------------------------


def the_tam(uv: UngVien, sid: str) -> dict[str, Any]:
    """Thẻ YAML tối thiểu cho `rule_coverage.evaluate_scenario` (câu giữ chỗ — rule_coverage không đọc câu)."""
    return {"id": sid, "family": sid, "source": "khung", "requester": {"user_id": uv.nguoi_gui, "role": "employee", "dept": "-",
            "tenure_days": 0}, "at": AT_MAC_DINH, "faults": [], "turns": ["-", {"on_confirm": True}],
            "gold": {"intents": [INTENT[uv.loai]], "need_type": "action", "expected_route": None, "expected_exit": None,
                     "approver_decision": "approve", "gold_doc_ids": [],
                     "action": {"type": uv.hanh_dong, "target": uv.doi_tuong, "requested_for": uv.lam_ho, "params": uv.tham_so},
                     "facts": uv.du_kien},
            "labels": {"annotator_1": None, "annotator_2": None}}  # fmt: skip


def cham_luat(ds: Sequence[UngVien], repo: Path) -> None:
    """Gán `quyet_dinh` (allow | approval_required | deny | none | error) + cảnh báo lệch seed, bằng đúng code rule_coverage."""
    policy = rc.load_policy(repo / "config" / "policy.json")
    meta = rc.load_action_metadata(repo / "config" / "action_metadata.yaml")
    cfg = rc.Config(
        rules=policy.rules,
        hours=policy.business_hours,
        metadata=meta.root,
        intents=rc.intents_of_actions(meta),
    )
    seed = rc.Seed(repo / "mock_services" / "seed.json")
    with tempfile.TemporaryDirectory() as tmp:
        for i, uv in enumerate(ds):
            path = Path(tmp) / f"K{i:05d}.yaml"
            path.write_text(
                yaml.safe_dump(
                    the_tam(uv, f"K{i:05d}"), allow_unicode=True, sort_keys=False
                ),
                encoding="utf-8",
            )
            res = rc.evaluate_scenario(path, seed, cfg)
            uv.quyet_dinh = res.decision if not res.error else "error"
            uv.canh_bao = list(res.warnings)


def khoa_bo_cu(the100: Path) -> set[tuple[str, str, str, str]]:
    out = set()
    for path in sorted(the100.glob("*.yaml")):
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        a = d["gold"]["action"]
        out.add(
            (
                d["requester"]["user_id"],
                a["type"],
                a["target"],
                a.get("requested_for") or d["requester"]["user_id"],
            )
        )
    return out


# ---- rút mẫu -----------------------------------------------------------------------------------------------------------


def khoa_lap(s: SeedGoc, uv: UngVien) -> tuple[str, str, str]:
    """Hai tình huống trùng nhau nếu cùng người gửi, cùng loại việc, cùng người bị tác động (vd gia hạn và cấp lại VPN cùng một máy)."""
    return (uv.nguoi_gui, uv.loai, chu_dich(s, uv))


def rut_mau(
    s: SeedGoc, ds: Sequence[UngVien], hat_giong: int = HAT_GIONG
) -> tuple[list[UngVien], list[UngVien], dict[str, int]]:
    """(chính, dự phòng, thiếu) — mỗi nhóm × loại rút `CHI_TIEU` thẻ, không lặp (người gửi, loại việc, người bị tác động) trên CẢ mẫu; dự phòng
    `DU_PHONG` thẻ mỗi nhóm từ phần còn lại. Thứ tự đầu vào cố định (sắp theo khoá) nên kết quả chỉ phụ thuộc hạt giống."""
    rng = random.Random(hat_giong)
    chinh: list[UngVien] = []
    du_phong: list[UngVien] = []
    thieu: dict[str, int] = {}
    da_lay: set[tuple[str, str, str]] = set()
    con_du_phong: list[list[UngVien]] = []
    for nhom in sorted(CHI_TIEU):
        con_lai: list[UngVien] = []
        for loai, k in sorted(CHI_TIEU[nhom].items()):
            pool = sorted(
                (u for u in ds if u.nhom == nhom and u.loai == loai),
                key=lambda u: (u.khoa, json.dumps(u.tham_so, sort_keys=True)),
            )
            rng.shuffle(pool)
            lay = 0
            for u in pool:
                key = khoa_lap(s, u)
                if lay < k and key not in da_lay:
                    chinh.append(u)
                    da_lay.add(key)
                    lay += 1
                else:
                    con_lai.append(u)
            if lay < k:
                thieu[f"{nhom}/{loai}"] = k - lay
        con_du_phong.append(con_lai)
    for nhom, con_lai in zip(sorted(CHI_TIEU), con_du_phong, strict=True):
        rng.shuffle(con_lai)
        n = 0
        for u in con_lai:
            key = khoa_lap(s, u)
            if n < DU_PHONG and key not in da_lay:
                du_phong.append(u)
                da_lay.add(key)
                n += 1
    return chinh, du_phong, thieu


# ---- ghi ------------------------------------------------------------------------------------------------------------------

COT_KHUNG = ("ma", "vai_tro", "nhom", "loai", "nguoi_gui", "hanh_dong", "doi_tuong", "lam_ho", "tham_so", "du_kien", "at",
             "viec", "du_kien_chu")  # fmt: skip


def dong_khung(s: SeedGoc, uv: UngVien, ma: str, vai_tro: str) -> dict[str, str]:
    return {"ma": ma, "vai_tro": vai_tro, "nhom": uv.nhom, "loai": uv.loai, "nguoi_gui": uv.nguoi_gui, "hanh_dong": uv.hanh_dong,
            "doi_tuong": uv.doi_tuong, "lam_ho": uv.lam_ho, "tham_so": json.dumps(uv.tham_so, ensure_ascii=False, sort_keys=True),
            "du_kien": json.dumps(uv.du_kien, ensure_ascii=False, sort_keys=True), "at": AT_MAC_DINH,
            "viec": uv.mo_ta, "du_kien_chu": uv.du_kien_chu}  # fmt: skip


def ghi_phieu_viet(path: Path, s: SeedGoc, dong: Sequence[dict[str, str]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.worksheet import Worksheet

    wb = Workbook()
    hd = wb.active
    assert isinstance(hd, Worksheet)  # Workbook() mới luôn có đúng 1 sheet thường
    hd.title = "Hướng dẫn"
    for i, t in enumerate(
        (
            "Phiếu viết thẻ — đo bổ sung RQ1 (đọc eval/bo-sung-rq1/HUONG-DAN-VIET.md trước khi viết).",
            "Mỗi dòng là một tình huống. Viết như nhân viên thật gõ vào khung chat IT: tiếng Việt tự nhiên, không cần đúng chính tả.",
            "Câu đầu nêu đủ: việc gì, cho ai, máy/thư mục/phần mềm nào, mức quyền, bao lâu (nếu có). Không chép nguyên câu ở cột 'Việc cần nhờ'.",
            "Trả lời 1–3: câu trả lời nếu hệ thống hỏi lại (theo thứ tự). Có thể để trống nếu câu đầu đã đủ.",
            "Không viết lý do kiểu 'vì luật…', không đoán hệ thống sẽ làm gì. Không dùng AI để viết hay sửa câu.",
            "Tình huống không thể xảy ra ngoài đời: ghi 'x' ở cột 'Không tự nhiên', để trống câu — sẽ thay bằng dòng dự phòng cùng nhóm.",
            "Không sửa các cột xám.",
        ),
        start=1,
    ):
        hd.cell(i, 1, t).alignment = Alignment(wrap_text=True)
    hd.column_dimensions["A"].width = 120
    ws = wb.create_sheet("Viết thẻ")
    head = ("Mã", "Vai trò", "Người gửi", "Việc cần nhờ", "Dữ kiện (người gửi có thể không biết)", "Câu đầu", "Trả lời 1",
            "Trả lời 2", "Trả lời 3", "Không tự nhiên", "Ghi chú")  # fmt: skip
    xam = PatternFill("solid", fgColor="EEEEEE")
    for j, h in enumerate(head, 1):
        c = ws.cell(1, j, h)
        c.font = Font(bold=True)
    for i, d in enumerate(dong, 2):
        vals = (
            d["ma"],
            d["vai_tro"],
            s.ten(d["nguoi_gui"]),
            d["viec"],
            d["du_kien_chu"],
        )
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v)
            c.fill = xam
            c.alignment = Alignment(wrap_text=True, vertical="top")
    for col, w in zip(
        "ABCDEFGHIJK", (7, 9, 30, 45, 40, 50, 30, 30, 30, 10, 20), strict=True
    ):
        ws.column_dimensions[col].width = w
    wb.save(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Đo bổ sung RQ1 — dựng khung tình huống (bước 1)"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hat-giong", type=int, default=HAT_GIONG)
    a = ap.parse_args(argv)
    if a.out.exists():
        print("DỪNG: --out đã tồn tại — cần thư mục mới")
        return 2
    s = SeedGoc(REPO / "mock_services" / "seed.json")
    tat_ca = list(liet_ke(s))
    cham_luat(tat_ca, REPO)
    loi = [u for u in tat_ca if u.quyet_dinh == "error"]
    if loi:
        print(f"DỪNG: {len(loi)} tổ hợp lỗi khi chấm luật (dữ kiện sai kiểu?)")
        return 2
    cu = khoa_bo_cu(REPO / "eval" / "the100")
    llm = [u for u in tat_ca if u.quyet_dinh == "none" and u.khoa not in cu]
    for u in llm:
        u.nhom = xep_nhom(s, u)
        u.mo_ta, u.du_kien_chu = mo_ta(s, u)
    dung = [u for u in llm if u.nhom]
    chinh, du_phong, thieu = rut_mau(s, dung, a.hat_giong)
    a.out.mkdir(parents=True)
    dong = [dong_khung(s, u, f"SB{i:02d}", "chính") for i, u in enumerate(chinh, 1)]
    dong += [
        dong_khung(s, u, f"SD{i:02d}", "dự phòng") for i, u in enumerate(du_phong, 1)
    ]
    with (a.out / "khung.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, COT_KHUNG)
        w.writeheader()
        w.writerows(dong)
    with (a.out / "ung-vien.csv").open("w", encoding="utf-8", newline="") as fh:
        wu = csv.writer(fh)
        wu.writerow(
            (
                "nhom",
                "loai",
                "nguoi_gui",
                "hanh_dong",
                "doi_tuong",
                "lam_ho",
                "tham_so",
                "canh_bao_seed",
            )
        )
        for u in sorted(llm, key=lambda u: (u.nhom, u.loai, u.khoa)):
            wu.writerow(
                (
                    u.nhom or "-",
                    u.loai,
                    *u.khoa,
                    json.dumps(u.tham_so, sort_keys=True),
                    len(u.canh_bao),
                )
            )
    ghi_phieu_viet(a.out / "phieu-viet.xlsx", s, dong)
    dem = Counter((u.quyet_dinh) for u in tat_ca)
    print(
        f"tổ hợp: {len(tat_ca)} · "
        + " · ".join(f"{k} {v}" for k, v in sorted(dem.items()))
    )
    print(f"đi lớp LLM, không trùng bộ cũ: {len(llm)} · dùng được (nhóm A–D): {len(dung)} · "
          + " · ".join(f"{k} {v}" for k, v in sorted(Counter(u.nhom or '-' for u in llm).items())))  # fmt: skip
    print(
        f"rút: chính {len(chinh)} · dự phòng {len(du_phong)} · hạt giống {a.hat_giong}"
        + (f" · THIẾU {thieu}" if thieu else "")
    )
    print(f"cảnh báo lệch seed (rule_coverage): {sum(len(u.canh_bao) for u in tat_ca)}")
    for name in ("khung.csv", "phieu-viet.xlsx", "ung-vien.csv"):
        print(f"{name} sha256 {sha256(a.out / name)}")
    return 1 if thieu else 0


if __name__ == "__main__":
    sys.exit(main())
