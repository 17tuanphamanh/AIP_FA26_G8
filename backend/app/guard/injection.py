"""L2 — mẫu injection (B02 mục 2; phase3 mục 8.4, 8.5; PLAN-3e Q-3e-5).

`match(text)`: L0 guard rồi so 11+ mẫu của `config/injection_patterns.json` trên CẢ bản có dấu lẫn bản không dấu
(`unidecode`), chữ thường, giữ dòng và gộp dòng (`normalize.match_forms`). Mẫu đầu tiên (theo thứ tự trong file) khớp
bất kỳ bản nào → `ScreenHit(id, group)`. Thuần, không gọi mạng, không log văn bản.

`TAU_BLOCK`, `TAU_PASS`: hai ngưỡng L3 của node `b02_screen` — hằng module ở Phase 3 (chưa có model `injection-clf`);
Phase 5 chuyển sang `constants`/`thresholds.json` của model (B02 mục 7). `TAU_PASS` = 0,10 theo phase3 8.5 (B02 §7 ghi
0,20 — lệch, "spec cần sửa"). ML-GAN: hai ngưỡng chỉ có hiệu lực khi `B2_CLASSIFIER_MODE=active`; `shadow` (mặc định)
chỉ ghi điểm.
"""

from dataclasses import dataclass

from app.guard.normalize import match_forms
from app.guard.patterns import InjectionPattern, injection_patterns
from app.settings import get_settings

TAU_BLOCK = 0.90  # p_mal ≥ → chặn (E0)
TAU_PASS = 0.10  # p_mal ≤ → qua; giữa hai ngưỡng → L4


@dataclass(frozen=True)
class ScreenHit:
    id: str  # vd "OVR-01" — vào security_events/audit, KHÔNG vào tin người dùng
    group: str  # override | impersonation | system_spoof | prompt_leak


def match(text: str, patterns: tuple[InjectionPattern, ...] | None = None) -> ScreenHit | None:
    forms = match_forms(text)
    for p in patterns if patterns is not None else injection_patterns(get_settings().config_dir):
        if any(p.pattern.search(form) for form in forms):
            return ScreenHit(p.id, p.group)
    return None
