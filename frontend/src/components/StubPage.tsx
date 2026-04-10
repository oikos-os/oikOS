interface Props {
  title: string;
  subtitle?: string;
}

export default function StubPage({ title, subtitle = "Coming soon." }: Props) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-neutral-500" data-testid={`stub-${title.toLowerCase().replace(/\s+/g, "-")}`}>
      <h2 className="text-2xl font-bold tracking-widest text-neutral-400 mb-2">{title}</h2>
      <p className="text-sm">{subtitle}</p>
    </div>
  );
}
