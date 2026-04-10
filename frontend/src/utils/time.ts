/**
 * Human-readable relative time from an ISO timestamp.
 *
 * @param iso  - ISO 8601 date string
 * @param compact - If true, returns short form ("now", "5m", "3h", "2d").
 *                  If false, returns verbose form ("just now", "5m ago", "3h ago", "2d ago").
 */
export function timeAgo(iso: string, compact = false): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return compact ? "now" : "just now";
  if (mins < 60) return compact ? `${mins}m` : `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return compact ? `${hrs}h` : `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return compact ? `${days}d` : `${days}d ago`;
}
