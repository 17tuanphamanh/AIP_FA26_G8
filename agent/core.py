"""Vong lap agent: dua cau hoi cho Claude, de Claude tu goi tool den khi xong.

Dung tool runner cua SDK (client.beta.messages.tool_runner) - no lo phan
"goi API -> chay tool -> nap ket qua lai -> goi tiep" thay minh.
Model mac dinh claude-opus-5 da bat adaptive thinking san, khong can khai bao them.
"""

import anthropic

from agent.config import CauHinh, doc_prompt
from agent.tools import DANH_SACH_TOOL


class Agent:
    def __init__(self, cau_hinh: CauHinh | None = None, tools: list | None = None):
        self.cau_hinh = cau_hinh or CauHinh.tu_moi_truong()
        self.tools = DANH_SACH_TOOL if tools is None else tools
        self.system = doc_prompt("system.md")
        self.client = anthropic.Anthropic(api_key=self.cau_hinh.api_key)
        # Lich su hoi thoai, giu lai de agent nho nhung luot truoc.
        self.lich_su: list[dict] = []

    def hoi(self, cau_hoi: str, in_tien_trinh: bool = False) -> str:
        """Gui mot cau hoi, tra ve phan tra loi dang van ban cua Claude."""
        self.lich_su.append({"role": "user", "content": cau_hoi})

        runner = self.client.beta.messages.tool_runner(
            model=self.cau_hinh.model,
            max_tokens=self.cau_hinh.max_tokens,
            system=self.system,
            tools=self.tools,
            messages=self.lich_su,
            max_iterations=self.cau_hinh.so_buoc_toi_da,
        )

        cuoi_cung = None
        for tin_nhan in runner:
            cuoi_cung = tin_nhan
            self.lich_su.append({"role": "assistant", "content": tin_nhan.content})
            ket_qua_tool = runner.generate_tool_call_response()
            if ket_qua_tool is not None:
                self.lich_su.append(ket_qua_tool)
            if in_tien_trinh:
                for khoi in tin_nhan.content:
                    if khoi.type == "tool_use":
                        print(f"  [tool] {khoi.name}({khoi.input})")

        if cuoi_cung is None:
            return "(khong nhan duoc phan hoi)"
        return lay_van_ban(cuoi_cung)


def lay_van_ban(tin_nhan) -> str:
    """Gop cac khoi text trong mot message thanh mot chuoi."""
    return "\n".join(
        khoi.text for khoi in tin_nhan.content if khoi.type == "text"
    ).strip()
