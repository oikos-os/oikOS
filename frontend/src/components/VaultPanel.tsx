import type { VaultStats } from "../types";

interface Props {
  stats: VaultStats | null;
}

export default function VaultPanel({ stats }: Props) {
  const total = stats?.total_rows ?? 0;
  const tiers = stats?.tier_breakdown ?? {};

  return (
    <section className="bg-[#242424] rounded-xl p-4">
      <h2 className="text-sm tracking-widest text-neutral-400 mb-3">VAULT</h2>

      <div className="space-y-2">
        <div className="flex justify-between text-neutral-300">
          <span>Indexed Chunks</span>
          <span className="text-white">{total.toLocaleString()}</span>
        </div>

        {Object.entries(tiers).map(([tier, count]) => (
          <div key={tier} className="flex justify-between text-neutral-400 text-sm">
            <span className="uppercase">{tier}</span>
            <span>{(count as number).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
