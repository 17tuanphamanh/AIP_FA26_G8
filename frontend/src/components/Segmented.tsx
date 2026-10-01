// Segmented của Bản 4 (B4MgrDashboard khoảng thời gian, B4MgrPolicy Bảng/JSON): nền `segmented`, ô chọn trắng.
export function Segmented<K extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex shrink-0 rounded-lg bg-segmented p-0.5">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          role="tab"
          aria-selected={value === option.key}
          data-key={option.key}
          onClick={() => onChange(option.key)}
          className={`h-8 rounded-md px-4 text-secondary ${value === option.key ? "bg-white font-semibold shadow-input" : ""}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
