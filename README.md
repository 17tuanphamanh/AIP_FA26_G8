<div align="center">

<img src="docs/assets/banner.svg" alt="AITHA — AI Agent tự động hoá IT Service Desk cấp 1, biết lúc nào phải hỏi con người" width="100%">

[![CI](https://github.com/17tuanphamanh/AIP_FA26_G8/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/17tuanphamanh/AIP_FA26_G8/actions/workflows/ci.yml)
[![Bản nộp](https://img.shields.io/github/v/release/17tuanphamanh/AIP_FA26_G8?label=b%E1%BA%A3n%20n%E1%BB%99p&color=7C3AED)](https://github.com/17tuanphamanh/AIP_FA26_G8/releases)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-FastAPI-009688?logo=fastapi&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
[![License: MIT](https://img.shields.io/badge/license-MIT-22C55E)](LICENSE)

**[Ảnh demo](#ảnh-demo) · [Cách quyết định](#cách-hệ-thống-quyết-định) · [Kết quả](#kết-quả-chính) · [Chạy thử](#chạy-nhanh-cho-thầy-và-hội-đồng) · [English](#english-summary)**

</div>

Nhân viên gõ yêu cầu IT bằng tiếng Việt: VPN, tài khoản, cài phần mềm, quyền thư mục. AITHA tự hiểu yêu cầu, tự kiểm tra
máy và hệ thống của người hỏi, rồi trả lời từ tài liệu nội bộ có trích nguồn hoặc tự thực hiện thao tác. Việc nhạy cảm
luôn đi qua luật cứng hoặc người duyệt, và mọi quyết định đều truy vết được.

> [!TIP]
> **Đóng góp chính của đồ án là cơ chế quyết định khi nào cần chuyển cho con người.** Luật chạy trước và LLM không ghi đè
> được. Khi chưa được hiệu chỉnh, LLM chỉ được chuyển việc lên người, không bao giờ tự làm.

## Ảnh demo

| | |
| --- | --- |
| ![Trả lời có nguồn](docs/anh-demo/01-tra-loi-co-nguon.png) | ![Phiếu duyệt](docs/anh-demo/02-phieu-duyet-rui-ro.png) |
| Kiểm tra máy của người hỏi rồi trả lời từ tài liệu nội bộ, có ghi nguồn | Phiếu duyệt gắn đúng một hành động, kèm đánh giá rủi ro và hạn 30 phút |
| ![Chặn tấn công](docs/anh-demo/03-chan-tan-cong.png) | ![Chính sách](docs/anh-demo/04-chinh-sach-quan-ly.png) |
| Câu tấn công bị chặn, trợ lý chỉ trả lời trung tính | Trưởng bộ phận IT chọn cách hệ thống ra quyết định, có lịch sử đổi |

Đủ 10 ca theo từng vai, 33 hình: [AITHA-anh-chup-demo-10-ca.pdf](docs/anh-demo/AITHA-anh-chup-demo-10-ca.pdf)

## Cách hệ thống quyết định

<img src="docs/assets/quyet-dinh.svg" alt="Luồng quyết định: luật chạy trước; việc luật không phủ sang LLM ước lượng rủi ro, khi chưa hiệu chỉnh chỉ được chuyển lên người duyệt; kiểm lại luật trước khi thực thi" width="100%">

- **Luồng 20 bước trên LangGraph**: xác thực, sàng lọc, hiểu và tách yêu cầu, chẩn đoán, trả lời hoặc đánh giá rủi ro,
  duyệt, thực thi, xác nhận, ghi nhật ký.
- **Lớp luật**: 7 luật cho phép, 14 luật cần duyệt, 2 luật cấm. Trưởng bộ phận duyệt bằng OTP, phiếu duyệt hết hạn sau
  30 phút.
- **Chặn prompt injection nhiều lớp**: mẫu cứng, model phân loại nhóm tự fine-tune và LLM chấm; mật khẩu, khoá và dữ liệu
  cá nhân được che trước khi gửi cho LLM.
- **RAG lai**: bge-m3 kết hợp BM25, rerank bằng bge-reranker-v2-m3. Không đủ căn cứ thì chuyển người, không trả lời bừa.
- **Kiểm thử**: hơn 11.400 test backend (unit, tích hợp với PostgreSQL thật, end-to-end) và 1.348 test giao diện. CI và
  hook chặn commit quét bí mật và chạy test.

<details>
<summary><b>Kiến trúc tổng thể</b></summary>
<br>

![Kiến trúc hệ thống](docs/kien-truc/kien-truc-gon.png)

Sơ đồ 8 tầng, luồng 20 bước và máy trạng thái: [docs/kien-truc/](docs/kien-truc/).

</details>

## Kết quả chính

Đo trên bản đóng băng `v1.0-freeze` với LLM thật. Chi tiết và giới hạn xem báo cáo đồ án.

| Phép đo | Kết quả |
| --- | --- |
| An toàn của lớp LLM (100 kịch bản có nhãn) | Bỏ sót **0/24** tình huống cần người; cận trên 95% là 11,7% |
| Chặn prompt injection (95 câu do người viết, gán nhãn mù) | Nhiều lớp bắt **82%**, riêng model nhóm 62%, Prompt Guard 2 20%; chặn nhầm 1/45 câu thường |
| Truy hồi tài liệu (34 bài, bản nộp) | Recall@5 = **1,000**; MRR = 0,845 |
| Tái lập | Người thứ hai chạy lại: khớp quyết định **90/90** ca |

Giới hạn đã biết:

- Lợi ích về chi phí khi kết hợp luật với LLM, so với chỉ dùng luật, **chưa chứng minh được**, vì bộ dữ liệu đánh giá
  còn nhỏ và độ đồng thuận gán nhãn thấp.
- Hệ thống mới chạy trên môi trường giả lập, chưa thử với người dùng thật.

## Chạy nhanh (cho thầy và hội đồng)

Cần Docker Desktop, git, make, Python 3, [uv](https://docs.astral.sh/uv/) và Node.js 24 (npm 11); trên Windows thì chạy
trong WSL2. Máy cần RAM 16 GB, ổ trống từ 25 GB và có Internet ở lần chạy đầu. Lần đầu mất khoảng 45–60 phút, chủ yếu để
tải model và build.

```bash
git clone https://github.com/17tuanphamanh/aip_fa26_g8 && cd aip_fa26_g8
# 1. Đặt file .env nhóm gửi riêng vào thư mục này (cùng chỗ với Makefile)
make models                    # 2 model chung, khoảng 4,5 GB
# 2. Giải nén aitha-model-freeze.zip (Drive nhóm gửi kèm) vào ml_models/
chmod -R a+rX ml_models models
make up && make ingest         # lần đầu 15–25 phút
# 3. Ở terminal thứ hai, rồi mở http://localhost:5173 bằng Chrome
cd frontend && npm ci && npm run dev
```

- **File `.env`** chứa khoá API nên không nằm trong repo. Nếu không có file này, tạo theo mục 3 của
  [hướng dẫn](docs/HUONG-DAN-CHAY.md); khi đó hệ thống chạy bằng LLM giả.
- **Model của nhóm**: sau khi giải nén phải có hai thư mục `ml_models/injection-clf/v3-seed123/` và
  `ml_models/intent-clf/v3.1-seed42-st/`. File `.env` đã trỏ sẵn tới chúng. Máy 8 GB RAM thì xoá 3 dòng `INTENT_*`
  trong `.env`.
- **Tài khoản demo** dùng chung mật khẩu `Demo@2026!`:
  - `an.nv`: nhân viên;
  - `ha.lt`: IT L1, duyệt phiếu;
  - `long.nh`: kỹ thuật viên L2;
  - `quan.tm`: trưởng bộ phận IT, cần đặt OTP một lần theo mục 8 của hướng dẫn.
- **Hệ thống giả lập**: http://127.0.0.1:8100/console
- **Tắt máy**: chạy `make down`, dữ liệu vẫn được giữ.

Hướng dẫn đầy đủ, kể cả các lỗi hay gặp: [docs/HUONG-DAN-CHAY.md](docs/HUONG-DAN-CHAY.md).

## Bản nộp và bản đo

| Mốc | Ở đâu | Dùng cho |
| --- | --- | --- |
| **Bản đo** | tag [`v1.0-freeze`](https://github.com/17tuanphamanh/AIP_FA26_G8/releases/tag/v1.0-freeze) (`bf94df2`, 29/10/2026) | Mọi số liệu RQ trong báo cáo đều đo trên bản này |
| **Bản nộp** | nhánh `main`, tag [`v1.1-nop-1411`](https://github.com/17tuanphamanh/AIP_FA26_G8/releases/tag/v1.1-nop-1411) (14/11/2026) | Mã nguồn nộp và video demo: gồm bản đo cộng các sửa đổi sau đó |

Cách tái lập số liệu, phần bản nộp khác bản đo và 4 cờ tính năng bật/tắt được xem ở
[docs/PHAT-TRIEN.md](docs/PHAT-TRIEN.md#bản-nộp-và-bản-đo).

## Tài liệu

| Tài liệu | Nội dung |
| --- | --- |
| [docs/HUONG-DAN-CHAY.md](docs/HUONG-DAN-CHAY.md) | Chạy thử từng bước và các lỗi hay gặp |
| [docs/PHAT-TRIEN.md](docs/PHAT-TRIEN.md) | Dựng môi trường dev, test, cấu trúc thư mục, quy ước commit |
| [docs/spec/](docs/spec/) | Đặc tả; các quyết định thiết kế D-xx ở [decisions.md](docs/spec/build/decisions.md) |
| [ml_models/MODELS.md](ml_models/MODELS.md) | Nguồn gốc, SHA-256 và ngưỡng của 2 model nhóm tự fine-tune |
| [PROGRESS.md](PROGRESS.md) | Nhật ký tiến độ theo từng phase |

> `CLAUDE.md` và thư mục `.claude/` là cấu hình agent hỗ trợ viết code. Nhóm dùng Claude Code và đã khai báo mức độ dùng
> AI trong báo cáo đồ án.

## English summary

<details>
<summary>AITHA in one minute: what it does, the stack, and the results</summary>
<br>

AITHA is an AI agent for Level-1 IT service desks that handles Vietnamese-language requests (VPN, accounts and passwords,
software installs, folder access).

A 20-step LangGraph workflow handles each request:

1. authenticates the user;
2. screens for prompt injection;
3. understands and splits the request;
4. proactively checks system state;
5. either answers from internal documents with citations (hybrid RAG) or prepares an action.

Every sensitive action goes through a deterministic rule layer (23 rules, strictest wins) and, when needed, a human
approver. Until it is calibrated, the LLM risk layer can only escalate to a human, never auto-approve. Each approval is
bound to a hash of one exact action, execution re-checks the rules, and every decision is logged.

**Stack:**

- Python 3.12, FastAPI and LangGraph;
- PostgreSQL and Qdrant;
- bge-m3, bge-reranker-v2-m3 and two fine-tuned XLM-RoBERTa classifiers;
- React 19, Vite and TypeScript;
- Docker Compose;
- LLM calls through a provider-agnostic gateway (DeepSeek in the demo).

**Results** (frozen build, real LLM):

- The LLM layer missed 0/24 cases that needed a human (95% upper bound 11.7%).
- The layered injection filter caught 82% of a blind 95-sentence test set, versus 20% for Prompt Guard 2.
- Retrieval Recall@5 was 1.0.
- An independent rerun reproduced 90/90 decisions.

Known limitation: the current small evaluation set does not yet show a cost benefit from combining rules and an LLM over
using rules alone.

</details>

## Nhóm thực hiện

| Thành viên | Phần chính |
| --- | --- |
| Phạm Tuấn Anh (nhóm trưởng) | Kiến trúc và đặc tả; luồng agent, cơ chế quyết định khi nào cần người, duyệt và thực thi, giao diện, hệ thống giả lập |
| Phạm Lưu Dương | Tầng giám sát; model chặn tấn công; thực nghiệm RQ1; dữ liệu RQ4 |
| Tạ Duy Anh | Tầng giám sát; model phân loại loại yêu cầu; thực nghiệm RQ3 và RQ4 |
| Dương Anh Quân | Tổng quan tài liệu; thực nghiệm RQ2; kiểm thử và chất lượng; dữ liệu RQ4 |

Giảng viên hướng dẫn: TS. Lê Đình Huynh, Trường Đại học FPT, cơ sở Hoà Lạc. Đồ án tốt nghiệp ngành Trí tuệ nhân tạo,
nhóm AIP491_G8, kỳ Fall 2026. Mã nguồn phát hành theo giấy phép [MIT](LICENSE).
