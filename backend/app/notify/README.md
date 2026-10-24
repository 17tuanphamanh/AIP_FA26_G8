notify_user — điểm gửi tin duy nhất; ticket con ghi child_notices (D-31). Xem docs/spec/build/01-kien-truc-project.md mục 3.
Email (notify-email): `notifier.py` bọc notify_user/notify_approver → 1 dòng `email_outbox` trong transaction của effects.once
(`outbox.py`); `email.py` soạn tiêu đề/thân/link; `smtp.py` gửi qua SMTP (worker job `send_emails`). Tắt mặc định (EMAIL_ENABLED).
