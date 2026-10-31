// Tranh minh hoạ cột trái màn đăng nhập (vẽ riêng cho đồ án, không lấy hình ngoài). Chỉ dùng màu token qua lớp
// Tailwind (`fill-*`, `stroke-*`, có độ trong suốt) — không mã màu trong file. Thuần trang trí: aria-hidden.
export function LoginArt({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 520 420" className={className} aria-hidden="true" focusable="false">
      {/* Nền đảo đẳng cự hai lớp */}
      <polygon points="260,250 500,330 260,410 20,330" className="fill-white/5" />
      <polygon points="260,220 470,290 260,360 50,290" className="fill-white/10" />
      <polygon points="260,236 420,290 260,344 100,290" className="fill-white/10" />

      {/* Khối trang trí nhỏ */}
      <polygon points="70,372 92,380 70,388 48,380" className="fill-white/20" />
      <polygon points="452,236 470,242 452,248 434,242" className="fill-white/20" />
      <polygon points="408,384 434,393 408,402 382,393" className="fill-white/10" />
      <circle cx="466" cy="70" r="5" className="fill-fpt-orange" />
      <circle cx="40" cy="150" r="4" className="fill-white/40" />
      <circle cx="488" cy="170" r="3" className="fill-white/40" />

      {/* Màn hình trò chuyện */}
      <g>
        <rect x="150" y="70" width="230" height="190" rx="16" className="fill-white/20" transform="translate(8 10)" />
        <rect x="150" y="70" width="230" height="190" rx="16" className="fill-white" />
        <rect x="150" y="70" width="230" height="34" rx="16" className="fill-selected" />
        <rect x="150" y="90" width="230" height="14" className="fill-selected" />
        <circle cx="170" cy="87" r="5" className="fill-fpt-orange" />
        <circle cx="186" cy="87" r="5" className="fill-done" />
        <circle cx="202" cy="87" r="5" className="fill-fpt-blue/40" />
        {/* Tin của người dùng */}
        <rect x="246" y="118" width="118" height="30" rx="12" className="fill-fpt-blue" />
        <rect x="258" y="130" width="74" height="6" rx="3" className="fill-white/80" />
        {/* Trả lời của trợ lý */}
        <circle cx="178" cy="176" r="13" className="fill-fpt-blue" />
        <path d="M172 176l4.5 4.5 8-8" className="fill-none stroke-fpt-orange" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="198" y="160" width="142" height="44" rx="12" className="fill-group" />
        <rect x="210" y="172" width="104" height="6" rx="3" className="fill-ink-3" />
        <rect x="210" y="186" width="74" height="6" rx="3" className="fill-ink-3/60" />
        {/* Ô nhập */}
        <rect x="166" y="222" width="198" height="24" rx="12" className="fill-group" />
        <circle cx="352" cy="234" r="8" className="fill-send" />
      </g>

      {/* Khiên — việc nhạy cảm chờ IT duyệt */}
      <g transform="translate(66 128)">
        <path d="M44 0l40 14v30c0 28-18 46-40 54C22 90 4 72 4 44V14z" className="fill-white/15" transform="translate(6 8)" />
        <path d="M44 0l40 14v30c0 28-18 46-40 54C22 90 4 72 4 44V14z" className="fill-fpt-orange" />
        <path d="M44 10l30 10v24c0 21-13 35-30 42-17-7-30-21-30-42V20z" className="fill-white/20" />
        <path d="M29 47l10 10 20-20" className="fill-none stroke-white" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      </g>

      {/* Phiếu yêu cầu đã giải quyết */}
      <g transform="translate(384 200) rotate(6)">
        <rect width="118" height="86" rx="12" className="fill-white/20" transform="translate(6 8)" />
        <rect width="118" height="86" rx="12" className="fill-white" />
        <rect x="14" y="16" width="56" height="7" rx="3.5" className="fill-ink-2/60" />
        <rect x="14" y="32" width="88" height="5" rx="2.5" className="fill-ink-3/60" />
        <rect x="14" y="44" width="70" height="5" rx="2.5" className="fill-ink-3/60" />
        <rect x="14" y="60" width="50" height="14" rx="7" className="fill-done/20" />
        <circle cx="24" cy="67" r="3.5" className="fill-done" />
        <circle cx="98" cy="64" r="12" className="fill-done" />
        <path d="M92 64l4 4 8-8" className="fill-none stroke-white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </g>

      {/* Chìa khoá — đặt lại mật khẩu */}
      <g transform="translate(120 286) rotate(-18)">
        <circle cx="22" cy="22" r="20" className="fill-none stroke-fpt-orange" strokeWidth="10" />
        <rect x="40" y="17" width="66" height="10" rx="5" className="fill-fpt-orange" />
        <rect x="84" y="25" width="10" height="16" rx="3" className="fill-fpt-orange" />
        <rect x="98" y="25" width="8" height="12" rx="3" className="fill-fpt-orange" />
      </g>

      {/* Bóng bóng thoại nhỏ bay lên */}
      <g transform="translate(372 64)">
        <path d="M0 10a10 10 0 0 1 10-10h44a10 10 0 0 1 10 10v18a10 10 0 0 1-10 10H22l-10 9v-9h-2A10 10 0 0 1 0 28z" className="fill-white/90" />
        <circle cx="20" cy="19" r="3.5" className="fill-fpt-blue" />
        <circle cx="32" cy="19" r="3.5" className="fill-fpt-blue/60" />
        <circle cx="44" cy="19" r="3.5" className="fill-fpt-blue/30" />
      </g>
    </svg>
  );
}
