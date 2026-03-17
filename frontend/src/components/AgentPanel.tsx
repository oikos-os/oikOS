import type { AgentEvalLatest, AgentGauntletLatest } from "../types";

interface Props {
  proposals: unknown[] | null;
  evalLatest: AgentEvalLatest | null;
  gauntletLatest: AgentGauntletLatest | null;
}

export default function AgentPanel({ proposals, evalLatest, gauntletLatest }: Props) {
  const pendingCount = proposals?.length ?? 0;
  const gauntletPassed = gauntletLatest?.passed ?? 0;
  const gauntletTotal = gauntletLatest?.total ?? 0;
  const regressions = gauntletLatest?.regressions ?? 0;
  const gauntletPerfect = gauntletTotal > 0 && gauntletPassed === gauntletTotal;

  return (
    <section className="bg-[#242424] rounded-xl p-4">
      <h2 className="text-sm tracking-widest text-neutral-400 mb-3">AGENTS</h2>

      <div className="space-y-3">
        <div className="flex justify-between text-neutral-300">
          <span>Consolidation</span>
          <span className={pendingCount > 0 ? "text-amber-400" : "text-neutral-500"}>
            {pendingCount} pending
          </span>
        </div>

        <div className="flex justify-between text-neutral-300">
          <span>Eval</span>
          {evalLatest?.avg_score != null ? (
            <span className="text-white">
              {(evalLatest.avg_score * 100).toFixed(0)}%
            </span>
          ) : (
            <span className="text-neutral-600">---</span>
          )}
        </div>

        <div className="flex justify-between text-neutral-300">
          <span>Gauntlet</span>
          {gauntletTotal > 0 ? (
            <span className={gauntletPerfect ? "text-green-500" : "text-red-500"}>
              {gauntletPassed}/{gauntletTotal}
              {regressions > 0 && (
                <span className="text-red-500 ml-2">
                  {regressions} REG
                </span>
              )}
            </span>
          ) : (
            <span className="text-neutral-600">---</span>
          )}
        </div>
      </div>
    </section>
  );
}
