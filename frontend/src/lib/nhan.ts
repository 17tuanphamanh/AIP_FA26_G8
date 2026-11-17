// Nhãn tiếng Việt cho mã nội bộ — NGUỒN CHỮ DUY NHẤT của giao diện (bảng từ ngữ ĐP chốt 26/10 23:10 + các câu [ĐX] ĐP duyệt
// 26/10 23:45, chặng N-NGU). Quy tắc hiển thị:
// - Nhân viên: chỉ chữ, KHÔNG BAO GIỜ thấy mã (E*, B*, R*, S_*, tên sự kiện) — `nhanNhanVien`; mã lạ → câu chung.
// - L1, L2, Trưởng BP IT: nhãn trước, mã sau chữ nhỏ màu nhạt — `nhanIT` + components/MaNhan.tsx; mã lạ → "Khác · <mã>".
// - Mã luật (R…) chỉ ở màn IT, luôn kèm mô tả — `luatIT`.
// Tra bảng bằng `ownEntry` (khoá riêng — "__proto__"/"constructor" từ server là mã lạ). Hàm thuần, không gọi mạng.
import { ownEntry } from "./lookup.ts";

export type Nhan = { nhan: string; goiY?: string };

// ---------------------------------------------------------------- mã kết thúc (exit code)
export const MA_KET_THUC: Readonly<Record<string, Nhan>> = {
  E0: { nhan: "Nghi tấn công, đã chặn", goiY: "Câu khớp mẫu tấn công hoặc LLM xác nhận tấn công" },
  E1: { nhan: "Ngoài phạm vi hoặc chưa rõ yêu cầu", goiY: "Không thuộc 4 loại việc, hoặc chưa xác định được ý định" },
  E2: { nhan: "Lỗi khi xử lý (AI hoặc công cụ)", goiY: "LLM, ml-service hoặc công cụ chẩn đoán lỗi, hết giờ" },
  E3: { nhan: "Thiếu tài liệu hướng dẫn", goiY: "Kho tri thức chưa có căn cứ đủ tin cậy; có cờ bổ sung KB" },
  E4: { nhan: "Thiếu thông tin từ người dùng", goiY: "Hỏi lại nhưng vẫn thiếu thông tin bắt buộc" },
  E5: { nhan: "Không đủ điều kiện tự xử lý", goiY: "Luật, đánh giá rủi ro hoặc kiểm tra lại trước khi thực hiện không cho tự làm" },
  E6: { nhan: "Quá hạn chờ duyệt", goiY: "Phiếu duyệt hết hạn" },
  E7: { nhan: "Thực hiện không thành công", goiY: "Hệ thống đích báo lỗi lúc thực hiện, ví dụ hết giấy phép" },
  E8: { nhan: "Người dùng báo chưa giải quyết", goiY: "Người dùng bấm \"Chưa ổn\"" },
  E9: { nhan: "Lỗi hệ thống bất ngờ", goiY: "Lỗi ngoài dự kiến ở bất kỳ bước nào" },
};
/** E1 với lý do `injection_suspected`: nhãn riêng (bảng). */
export const E1_NGHI_TAN_CONG: Nhan = { nhan: "Nghi tấn công, cần người xem", goiY: "Model chặn tấn công nghi ngờ nhưng LLM chưa xác nhận" };

/** M2 (ĐP 08/11): E5 tách theo lý do — lớp AI lỗi (mọi lỗi: chưa bật hay sập đều một nhãn) khác luật cấm. Không nêu tên lỗi nội bộ. */
export const E5_AI_LOI: Nhan = { nhan: "Chưa đánh giá được rủi ro — chuyển kỹ thuật viên", goiY: "Không có kết quả đánh giá rủi ro tự động — cần kỹ thuật viên đánh giá thủ công" };
export const E5_CAM: Nhan = { nhan: "Không được phép theo chính sách", goiY: "Luật chính sách cấm thao tác này — không thực hiện lại" };
const E5_THEO_LY_DO: Readonly<Record<string, Nhan>> = { llm_layer_disabled: E5_AI_LOI, policy_deny: E5_CAM };

/** Nhãn mã kết thúc có xét lý do (E1 + injection_suspected → nhãn riêng; E5 + llm_layer_disabled / policy_deny → nhãn riêng). */
export function maKetThuc(code: string, reasonDetail?: string | null): Nhan | null {
  if (code === "E1" && reasonDetail === "injection_suspected") return E1_NGHI_TAN_CONG;
  if (code === "E5" && reasonDetail) {
    const rieng = ownEntry<Nhan | null>(E5_THEO_LY_DO, reasonDetail, null);
    if (rieng) return rieng;
  }
  return ownEntry<Nhan | null>(MA_KET_THUC, code, null);
}

// ---------------------------------------------------------------- lý do (escalations.reason_detail)
/** 4 lý do E5 theo bảng + các lý do khác [ĐX duyệt] (trùng tên sự kiện → cùng câu, xem `SU_KIEN`). */
const LY_DO_RIENG: Readonly<Record<string, string>> = {
  recheck_failed: "Kiểm tra lại trước khi thực hiện không đạt",
  llm_layer_disabled: "Lớp AI không phản hồi",
  llm_high_risk: "AI đánh giá rủi ro cao",
  approval_target_unverified: "Không xác minh được người hưởng lợi",
  policy_deny: "Không được phép theo chính sách", // M2 (ĐP 08/11)
  no_grounding: "Không có tài liệu đủ căn cứ",
  screening_unavailable: "Chưa kiểm tra an toàn được",
  multi_intent_not_enabled: "Yêu cầu nhiều ý chưa bật",
  out_of_scope: "Ngoài phạm vi hỗ trợ",
  reverse_action_requested: "Xin thu hồi, khoá, gỡ, huỷ hoặc báo mất máy / lộ mật khẩu — hệ thống không tự làm", // D-84 (12/11)
};

// ---------------------------------------------------------------- cách xử lý, bên quyết định
export const HUONG_XU_LY: Readonly<Record<string, string>> = {
  AUTO: "Tự xử lý",
  HITL: "Chờ IT duyệt",
  ESCALATE_L2: "Chuyển kỹ thuật viên L2",
};
/** Đường xử lý trong nhật ký (`resolution_path`) [ĐX duyệt]. */
export const DUONG_XU_LY: Readonly<Record<string, string>> = {
  auto: "Tự xử lý",
  approved: "Xử lý sau khi IT duyệt",
  rejected: "Bị từ chối",
  escalated: "Chuyển kỹ thuật viên L2",
  deflected: "Trả lời từ tài liệu",
};
export const BEN_QUYET_DINH: Readonly<Record<string, string>> = {
  rule: "Theo luật",
  llm: "Theo đánh giá của AI",
  model: "Theo model chặn tấn công",
};

// ---------------------------------------------------------------- bước xử lý (nhật ký)
export const BUOC: Readonly<Record<string, string>> = {
  B1: "Xác thực người gửi",
  B2: "Kiểm tra tấn công",
  B3: "Phân loại và tách yêu cầu",
  B4: "Phân loại và tách yêu cầu",
  B5: "Phân loại và tách yêu cầu",
  "B3/B4": "Phân loại và tách yêu cầu",
  B6: "Chẩn đoán trên hệ thống",
  B7: "Chẩn đoán trên hệ thống",
  B8: "Tra cứu tài liệu",
  B9: "Tra cứu tài liệu",
  B10: "Trả lời từ tài liệu",
  B11: "Bổ sung thông tin",
  B12: "Đánh giá rủi ro",
  "B13/B14": "Đánh giá rủi ro",
  B13: "Đánh giá rủi ro",
  B14: "Đánh giá rủi ro",
  B15: "Phê duyệt",
  B16: "Phê duyệt",
  B15_APPROVER: "Tìm người duyệt",
  B17: "Thực hiện",
  B18: "Thực hiện",
  B17_RECHECK: "Kiểm tra lại trước khi thực hiện",
  B19: "Xác nhận với người dùng",
  B20: "Ghi nhận và chuyển người",
  runner: "Điều phối hệ thống",
  OVERRIDE: "Ghi đè của IT",
};

// ---------------------------------------------------------------- sự kiện (tên snake_case) [ĐX duyệt]
export const SU_KIEN: Readonly<Record<string, string>> = {
  identity_established: "Đã xác thực người gửi",
  identity_unverifiable: "Không xác thực được người gửi",
  role_unmappable: "Không xác định được vai trò",
  screened: "Đã kiểm tra tấn công",
  injection_detected: "Phát hiện tấn công, đã chặn",
  injection_suspected: "Nghi tấn công, cần người xem",
  injection_in_reply: "Nghi tấn công trong câu trả lời bổ sung",
  guard_unavailable: "Chưa kiểm tra an toàn được",
  classifier_unavailable: "Chưa phân loại được (dịch vụ lỗi)",
  intent_classified: "Đã phân loại yêu cầu",
  // Lô Q1 + Q12 (ĐP chốt 09/11): hỏi lại loại yêu cầu khi câu mơ hồ; câu hỏi IT chung không cần kiểm tra hệ thống
  triage_asked: "Hỏi lại loại yêu cầu",
  triage_reply: "Người dùng trả lời câu hỏi loại yêu cầu",
  diagnosis_not_applicable: "Không cần kiểm tra hệ thống (câu hỏi hướng dẫn)",
  intent_low_confidence: "Chưa chắc loại yêu cầu",
  intent_out_of_scope: "Ngoài phạm vi hỗ trợ",
  intent_not_enabled: "Loại yêu cầu chưa bật",
  reverse_action_requested: "Xin thu hồi, khoá, gỡ, huỷ hoặc báo mất máy / lộ mật khẩu — chuyển kỹ thuật viên", // D-84 (12/11)
  split: "Đã tách thành nhiều ý",
  split_span_invalid: "Tách ý không hợp lệ",
  child_started: "Bắt đầu xử lý một ý",
  child_not_runnable: "Ý này không xử lý được",
  children_aggregated: "Đã tổng hợp các ý",
  digest_sent: "Đã gửi tin tổng hợp",
  parent_woken: "Tiếp tục yêu cầu gốc",
  diagnosed: "Đã chẩn đoán",
  diagnosis_skipped: "Bỏ qua chẩn đoán",
  tool_system_error: "Công cụ chẩn đoán lỗi",
  new_slot_rediagnose: "Chẩn đoán lại theo thông tin mới",
  retrieved: "Đã tra cứu tài liệu",
  retrieval_error: "Tra cứu tài liệu lỗi",
  rag_system_error: "Hệ thống tra cứu lỗi",
  no_evidence: "Không có tài liệu đủ căn cứ",
  invalid_citation: "Trích dẫn tài liệu không hợp lệ",
  cannot_answer: "Không trả lời được từ tài liệu",
  deflected_info_only: "Đã trả lời hướng dẫn",
  output_guard_block: "Câu trả lời bị chặn khi kiểm tra",
  needs_action: "Cần thao tác trên hệ thống",
  no_procedure: "Chưa có quy trình cho thao tác này",
  action_built: "Đã chuẩn bị thao tác",
  asked: "Đã hỏi thêm người dùng",
  user_replied: "Người dùng đã bổ sung",
  reply_timeout: "Hết hạn chờ người dùng trả lời",
  clarify_timeout: "Hết hạn chờ bổ sung",
  clarification_exhausted: "Hỏi lại nhiều lần vẫn thiếu thông tin",
  max_clarification_reached: "Đã hỏi lại tối đa",
  off_topic_twice: "Trả lời lạc đề hai lần",
  risk_decided: "Đã đánh giá rủi ro",
  llm_unavailable: "Lớp AI không phản hồi",
  llm_schema_error: "AI trả kết quả sai dạng",
  llm_layer_disabled: "Lớp AI không phản hồi",
  llm_high_risk: "AI đánh giá rủi ro cao",
  target_check_error: "Không kiểm tra được đối tượng",
  queued: "Đã gửi phiếu duyệt",
  no_valid_approver: "Không có người duyệt hợp lệ",
  approver_lookup_error: "Tra cứu người duyệt lỗi",
  approver_sync_unavailable: "Chưa đồng bộ được người duyệt",
  approval_target_unverified: "Không xác minh được người hưởng lợi",
  approved: "Đã duyệt",
  rejected: "Đã từ chối",
  approval_timeout: "Quá hạn chờ duyệt",
  late_event: "Thao tác đến muộn, bỏ qua",
  approver_no_longer_valid: "Người duyệt không còn hợp lệ",
  person_no_longer_valid: "Người hưởng lợi không còn hợp lệ",
  action_plan_changed_since_approval: "Thao tác đã đổi sau khi duyệt",
  recheck_failed: "Kiểm tra lại trước khi thực hiện không đạt",
  executed_ok: "Đã thực hiện",
  exec_failed: "Thực hiện lỗi",
  execution_failed: "Thực hiện lỗi",
  exec_interrupted: "Thực hiện bị gián đoạn",
  execution_interrupted: "Thực hiện bị gián đoạn",
  user_confirmed: "Người dùng xác nhận đã ổn",
  user_reported_unresolved: "Người dùng báo chưa giải quyết",
  followup_reply: "Người dùng nhắn tiếp sau câu trả lời", // B4 (12/11): B19 hỏi tiếp sau câu trả lời KB
  closed: "Đã ghi nhận và kết thúc",
  escalation_closed: "Kỹ thuật viên đóng ca",
  max_loops_exceeded: "Vượt số vòng xử lý",
  turn_budget_exceeded: "Hết thời gian cho lượt xử lý",
  recursion_limit: "Vượt giới hạn xử lý",
  recover_exhausted: "Khôi phục không thành công",
  unhandled_exception: "Lỗi hệ thống bất ngờ",
  override_recorded: "IT đã ghi đè quyết định",
  privacy_secret_redacted: "Đã ẩn thông tin nhạy cảm",
  finalize_failed_permanent: "Ghi kết thúc thất bại",
  out_of_scope: "Ngoài phạm vi hỗ trợ",
};

// ---------------------------------------------------------------- trạng thái ticket (S_*)
/** Nhãn trạng thái cho nhân sự IT (bảng + [ĐX duyệt]). Màn nhân viên dùng routes/employee/status.ts (câu tiến trình). */
export const TRANG_THAI: Readonly<Record<string, string>> = {
  S_NEW: "Đang tiếp nhận",
  S_SCREENING: "Đang tiếp nhận",
  S_CLASSIFYING: "Đang tiếp nhận",
  S_DIAGNOSING: "Đang chẩn đoán",
  S_RETRIEVING: "Đang tra cứu tài liệu",
  S_ASSESSING: "Đang đánh giá rủi ro",
  S_EXECUTING: "Đang thực hiện",
  S_CLARIFYING: "Chờ người dùng bổ sung",
  S_PENDING_APPROVAL: "Chờ IT duyệt",
  S_CONFIRMING: "Chờ người dùng xác nhận",
  S_ESCALATED: "Đã chuyển kỹ thuật viên",
  S_RESOLVED: "Đã giải quyết",
  S_REJECTED: "Bị từ chối",
  S_BLOCKED: "Đã chặn",
};

/** Nhãn loại yêu cầu (intent) — như backend/app/domain/messages.py; khoá lạ → null (màn tự hiện "Khác · mã"). */
export const LOAI_YEU_CAU: Readonly<Record<string, string>> = {
  vpn: "VPN",
  account: "Tài khoản",
  software: "Phần mềm",
  access: "Quyền truy cập",
  it_help: "Hỏi đáp IT", // D-76 (ĐP chốt 09/11): intent chỉ-trả-lời — câu hỏi IT chung trả lời từ KB general
};

// ---------------------------------------------------------------- hàm dùng chung
export type Loai = "ma_ket_thuc" | "ly_do" | "huong_xu_ly" | "duong_xu_ly" | "ben_quyet_dinh" | "buoc" | "su_kien" | "trang_thai" | "loai_yeu_cau";

function bang(loai: Loai, ma: string): Nhan | null {
  switch (loai) {
    case "ma_ket_thuc":
      return ownEntry<Nhan | null>(MA_KET_THUC, ma, null);
    case "ly_do": {
      const t = ownEntry<string | null>(LY_DO_RIENG, ma, null) ?? ownEntry<string | null>(SU_KIEN, ma, null);
      return t === null ? null : { nhan: t };
    }
    default: {
      const table = { huong_xu_ly: HUONG_XU_LY, duong_xu_ly: DUONG_XU_LY, ben_quyet_dinh: BEN_QUYET_DINH, buoc: BUOC, su_kien: SU_KIEN, trang_thai: TRANG_THAI, loai_yeu_cau: LOAI_YEU_CAU }[loai];
      const t = ownEntry<string | null>(table, ma, null);
      return t === null ? null : { nhan: t };
    }
  }
}

export const KHAC = "Khác";

/** Nhân sự IT: nhãn + mã gốc (mã lạ → nhãn "Khác"). Mã luôn đi kèm, hiện chữ nhỏ màu nhạt (components/MaNhan.tsx). */
export function nhanIT(loai: Loai, ma: string): { nhan: string; ma: string; goiY?: string } {
  const n = bang(loai, ma);
  return n ? { nhan: n.nhan, ma, ...(n.goiY ? { goiY: n.goiY } : {}) } : { nhan: KHAC, ma };
}

/** Chuỗi phẳng "Nhãn · mã" (cho `title`, câu lỗi, chỗ không dựng được component). */
export const nhanITChu = (loai: Loai, ma: string): string => {
  const n = nhanIT(loai, ma);
  return `${n.nhan} · ${n.ma}`;
};

/** Câu chung cho nhân viên khi mã lạ — không bao giờ lộ mã. */
export const NHAN_VIEN_KHAC = "Đang xử lý yêu cầu";

/** Nhân viên: CHỈ chữ; mã lạ → câu chung (không "Khác · mã"). */
export function nhanNhanVien(loai: Loai, ma: string | null | undefined): string {
  if (!ma) return NHAN_VIEN_KHAC;
  return bang(loai, ma)?.nhan ?? NHAN_VIEN_KHAC;
}

/** Mã luật cho màn IT: "Mô tả · R18"; chưa có mô tả → "Luật chưa có mô tả · R18". */
export const LUAT_KHONG_MO_TA = "Luật chưa có mô tả";
export function luatIT(ruleId: string, moTa: string | null | undefined): { nhan: string; ma: string } {
  const m = moTa?.trim();
  return { nhan: m ? m : LUAT_KHONG_MO_TA, ma: ruleId };
}

/** "Escalation #1253" → "Ca #1253". */
export const caSo = (id: number | string): string => `Ca #${id}`;

/** Tooltip "Chuyển L2 (có trọng số)" — tỉ lệ theo `N3_WEIGHTS` của backend (monitor/metrics.py: 0,7 / 0,2 / 0,1). */
export const GOI_Y_TRONG_SO = "Tính theo tỉ lệ 70/20/10 giữa ca thường, ca cần duyệt và ca nhạy cảm.";


// ---------------------------------------------------------------- thông báo của nhân viên (N-TB, hợp đồng thông báo §1)
// Câu chữ mới [ĐX] (bảng từ ngữ giao diện chưa có mục thông báo) — chờ duyệt.

/** Nhãn ngắn của `result` (chip trên mỗi dòng thông báo). Khoá lạ → không có nhãn (parser đã chặn khoá lạ). */
export const KET_QUA_THONG_BAO: Readonly<Record<string, string>> = {
  approved: "Đã duyệt",
  rejected: "Bị từ chối",
  completed: "Đã xử lý xong",
  confirmed_denial: "Giữ quyết định từ chối",
  reopened_as_new: "Cần gửi yêu cầu mới",
  in_progress: "Đang xử lý", // D-99
  raised: "Chuyển cấp cao hơn", // D-99
};

/** Câu chung theo `result` — thay chữ của server khi chữ đó có dáng mã nội bộ (fail-closed). */
export const CAU_THONG_BAO: Readonly<Record<string, string>> = {
  approved: "IT đã duyệt yêu cầu của bạn.",
  rejected: "IT đã từ chối yêu cầu của bạn.",
  completed: "Kỹ thuật viên đã xử lý xong yêu cầu của bạn.",
  confirmed_denial: "Kỹ thuật viên đã xem lại và giữ quyết định từ chối.",
  reopened_as_new: "Kỹ thuật viên đề nghị bạn gửi một yêu cầu mới cho việc này.",
  in_progress: "Kỹ thuật viên đã nhận yêu cầu của bạn và đang xử lý.", // D-99
  raised: "Yêu cầu của bạn đã được chuyển lên cấp xử lý cao hơn.", // D-99
};

/** Câu chung theo `kind` khi `result` không có câu (dự phòng; parser đã chặn khoá lạ). */
export const CAU_THONG_BAO_LOAI: Readonly<Record<string, string>> = {
  approval_decided: "IT đã có quyết định cho yêu cầu của bạn.",
  escalation_closed: "Kỹ thuật viên đã xử lý xong ca của bạn.",
  escalation_claimed: "Kỹ thuật viên đã nhận yêu cầu của bạn.", // D-99
  escalation_raised: "Yêu cầu của bạn đã được chuyển lên cấp xử lý cao hơn.", // D-99
};
export const CAU_THONG_BAO_KHAC = "Yêu cầu của bạn có cập nhật mới.";

/** Dáng mã nội bộ (mã kết thúc E*, bước B*, luật R*, trạng thái S_*) — có là KHÔNG hiện chữ server cho nhân viên. */
export const DANG_MA_NOI_BO = /\bE\d\b|\bB\d{1,2}\b|\bR\d+\b|S_[A-Z]/;

/** Chữ thông báo cho nhân viên: chữ server nguyên văn; rỗng hoặc có dáng mã → câu chung theo result/kind. */
export function cauThongBao(item: { kind: string; result: string; text: string }): string {
  const text = item.text.trim();
  if (text !== "" && !DANG_MA_NOI_BO.test(text)) return text;
  return ownEntry<string | null>(CAU_THONG_BAO, item.result, null) ?? ownEntry(CAU_THONG_BAO_LOAI, item.kind, CAU_THONG_BAO_KHAC);
}
