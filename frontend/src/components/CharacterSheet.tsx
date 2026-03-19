import { useApi } from "../hooks/useApi";

interface RpgStats {
  level: number;
  total_xp: number;
  xp_progress: number;
  xp_needed: number;
  xp_pct: number;
  stats: Record<string, number>;
  achievements_unlocked: string[];
  achievements_all: string[];
  events_processed: number;
  counters: Record<string, number>;
}

const STAT_LABELS: Record<string, string> = {
  intelligence: "INT",
  defense: "DEF",
  memory: "MEM",
  constitution: "CON",
  discipline: "DIS",
};

const ACHIEVEMENT_LABELS: Record<string, string> = {
  crucible_survivor: "Crucible Survivor",
  iron_spine: "Iron Spine",
  the_face: "The Face",
  perfect_defense: "Perfect Defense",
  memory_keeper: "Memory Keeper",
  century: "Century",
  half_thousand: "Half-Thousand",
  first_blood: "First Blood",
};

export default function CharacterSheet() {
  const { data } = useApi<RpgStats>("/api/rpg/stats", 30_000);

  if (!data) {
    return (
      <div className="bg-[#242424] rounded-xl p-4 text-neutral-600 text-sm">
        Loading character data...
      </div>
    );
  }

  return (
    <section className="bg-[#242424] rounded-xl p-4" data-testid="character-sheet">
      <h2 className="text-sm tracking-widest text-neutral-400 mb-3">
        CHARACTER SHEET
      </h2>

      {/* Level + XP */}
      <div className="mb-4">
        <div className="flex justify-between mb-1">
          <span className="text-amber-500 font-bold">LVL {data.level}</span>
          <span className="text-neutral-400 text-sm">
            {data.total_xp.toLocaleString()} XP
          </span>
        </div>
        <div className="h-2 bg-neutral-700/50 rounded-full w-full">
          <div
            className="h-full bg-amber-600 rounded-full"
            style={{ width: `${data.xp_pct}%` }}
          />
        </div>
        <div className="text-xs text-neutral-500 mt-0.5">
          {data.xp_progress} / {data.xp_needed} to next level
        </div>
      </div>

      {/* Stats */}
      <div className="space-y-2 mb-4">
        {Object.entries(data.stats).map(([key, value]) => (
          <div key={key}>
            <div className="flex justify-between text-sm mb-0.5">
              <span className="text-neutral-300 tracking-wider">
                {STAT_LABELS[key] ?? key.toUpperCase()}
              </span>
              <span className="text-white">{value}</span>
            </div>
            <div className="h-1.5 bg-neutral-700/50 rounded-full w-full">
              <div
                className="h-full bg-neutral-500 rounded-full"
                style={{ width: `${value}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Achievements */}
      <div>
        <h3 className="text-xs tracking-widest text-neutral-500 mb-2">
          ACHIEVEMENTS
        </h3>
        <div className="grid grid-cols-2 gap-1">
          {data.achievements_all.map((id) => {
            const unlocked = data.achievements_unlocked.includes(id);
            return (
              <div
                key={id}
                className={`text-xs px-2 py-1 rounded-md ${
                  unlocked
                    ? "bg-amber-900/30 text-amber-500"
                    : "bg-neutral-800/50 text-neutral-700"
                }`}
                data-testid={unlocked ? "achievement-unlocked" : "achievement-locked"}
              >
                {ACHIEVEMENT_LABELS[id] ?? id}
              </div>
            );
          })}
        </div>
      </div>

      {/* Events counter */}
      <div className="mt-3 text-xs text-neutral-500">
        {data.events_processed.toLocaleString()} events processed
      </div>
    </section>
  );
}
