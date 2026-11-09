"""Tên view SQL của M9 (hợp đồng A0 mục 3). View được tạo ở migration M9 của chặng A1 (+ GRANT SELECT cho
app_monitor); mọi đếm ticket đi qua `V_LEAF` (`is_parent = false`, D-30). F12: `V_CHILD_NOTICES` (migration 0011 —
hộp thư con, chỉ notice của con là lá, không cột `body`)."""

V_LEAF = "v_leaf"
V_DECISIONS = "v_decisions"
V_L2_QUEUE = "v_l2_queue"
V_CHILD_NOTICES = "v_child_notices"
