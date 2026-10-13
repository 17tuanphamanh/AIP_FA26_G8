"""Suy luận từ kết quả chẩn đoán (B6) — hàm THUẦN, không I/O, không LLM (B06 mục 3). Mỗi intent một module. Đầu ra
`(slots bổ sung, facts)`: `facts` là DỮ KIỆN cho luật M5, chỉ đọc từ dữ liệu tool (G-01).

T20a (phase5 5.1.5, PLAN-T20a TQ-3): `DIAGNOSERS` — MỘT nguồn cho B6 và B11 (`graph.nodes.*` không import lẫn nhau). Ba intent mới cùng
giao diện `TOOLS`, `calls`, `target_calls`, `infer`. `vpn` KHÔNG nằm trong bảng: node giữ nguyên dòng code VPN cũ (`vpn.calls` có chữ ký
`(requester_id, device_id)`).
"""

from collections.abc import Mapping
from types import ModuleType

from app.tools.diagnosis import access, account, software

DIAGNOSERS: Mapping[str, ModuleType] = {"account": account, "software": software, "access": access}
