import type { Toast } from "../hooks/useNotifications";

interface Props {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

const LEVEL_STYLES: Record<string, string> = {
  critical: "border-red-600/60 bg-red-950 text-red-300",
  error: "border-red-700/60 bg-red-950/80 text-red-400",
  warning: "border-amber-600/60 bg-amber-950/80 text-amber-400",
  info: "border-neutral-700/50 bg-[#242424] text-neutral-400",
};

export default function ToastContainer({ toasts, onDismiss }: Props) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-14 right-4 z-50 flex flex-col gap-2 max-w-sm" data-testid="toast-container">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`border rounded-xl px-4 py-3 text-xs shadow-lg ${LEVEL_STYLES[t.level] ?? LEVEL_STYLES.info}`}
          data-testid={`toast-${t.level}`}
        >
          <div className="flex justify-between items-start gap-3">
            <div>
              <div className="font-bold tracking-wider text-[10px] mb-1">{t.title}</div>
              <div>{t.message}</div>
            </div>
            <button
              onClick={() => onDismiss(t.id)}
              className="text-neutral-600 hover:text-neutral-400 text-sm leading-none shrink-0 transition-colors"
            >
              x
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
