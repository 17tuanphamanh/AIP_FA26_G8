// Segmented của Bản 4 (B4MgrDashboard khoảng thời gian, B4MgrPolicy Bảng/JSON): nền `segmented`, ô chọn trắng. Ô trắng là
// một lớp riêng trượt theo lựa chọn (các ô rộng bằng nhau), nên đổi tab thấy rõ đi từ đâu sang đâu.
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
  const index = Math.max(
    0,
    options.findIndex((option) => option.key === value),
  );
  return (
    <div role="tablist" aria-label={label} className="relative grid shrink-0 auto-cols-fr grid-flow-col rounded-lg bg-segmented p-0.5">
      <span
        aria-hidden="true"
        className="absolute top-0.5 bottom-0.5 left-0.5 rounded-md bg-white shadow-input transition-transform duration-250 ease-soft"
        style={{ width: `calc((100% - 4px) / ${options.length})`, transform: `translateX(${index * 100}%)` }}
      />
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          role="tab"
          aria-selected={value === option.key}
          data-key={option.key}
          onClick={() => onChange(option.key)}
          className={`relative h-8 rounded-md px-4 text-secondary max-lg:min-h-11 max-lg:px-3 ${value === option.key ? "font-semibold" : "text-ink-2 hover:text-ink"}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
