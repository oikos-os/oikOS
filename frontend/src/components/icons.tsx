interface IconProps {
  className?: string;
}

const svg = (d: string) =>
  function Icon({ className }: IconProps) {
    return (
      <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d={d} />
      </svg>
    );
  };

export const IconMenu = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <path d="M3 5h14M3 10h14M3 15h14" />
  </svg>
);

export const IconPlus = svg("M10 4v12M4 10h12");

export const IconSearch = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <circle cx="8.5" cy="8.5" r="5" />
    <path d="M12.5 12.5L17 17" />
  </svg>
);

export const IconDashboard = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="6" height="6" rx="1" />
    <rect x="11" y="3" width="6" height="6" rx="1" />
    <rect x="3" y="11" width="6" height="6" rx="1" />
    <rect x="11" y="11" width="6" height="6" rx="1" />
  </svg>
);

export const IconScene = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="4" width="16" height="12" rx="1" />
    <path d="M2 13l4-4 3 3 4-5 5 6" />
  </svg>
);

export const IconWorkflow = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="5" cy="5" r="2" />
    <circle cx="15" cy="5" r="2" />
    <circle cx="10" cy="15" r="2" />
    <path d="M6.5 6.5L9 13M13.5 6.5L11 13" />
  </svg>
);

export const IconAgents = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="10" cy="6" r="3" />
    <path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6" />
  </svg>
);

export const IconMicrophone = svg("M10 2a2.5 2.5 0 00-2.5 2.5v5a2.5 2.5 0 005 0v-5A2.5 2.5 0 0010 2zM5 9a5 5 0 0010 0M10 14v4M7 18h6");

export const IconChevronDown = svg("M5 7l5 5 5-5");

export const IconCopy = svg("M6 4h8a2 2 0 012 2v8M4 8h8a2 2 0 012 2v6a2 2 0 01-2 2H6a2 2 0 01-2-2v-6a2 2 0 012-2z");

export const IconStar = svg("M10 2l2.4 5.2L18 8l-4 3.9.9 5.6L10 14.7 5.1 17.5l.9-5.6L2 8l5.6-.8L10 2z");

export const IconStarFilled = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 2l2.4 5.2L18 8l-4 3.9.9 5.6L10 14.7 5.1 17.5l.9-5.6L2 8l5.6-.8L10 2z" />
  </svg>
);

export const IconAttach = svg("M14.5 10l-5 5a3 3 0 01-4.24-4.24l7-7a2 2 0 012.83 2.83l-7 7a1 1 0 01-1.42-1.42l5-5");

export const IconSettings = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="10" cy="10" r="3" />
    <path d="M10 1v3M10 16v3M1 10h3M16 10h3M3.5 3.5l2 2M14.5 14.5l2 2M3.5 16.5l2-2M14.5 5.5l2-2" />
  </svg>
);

export const IconChat = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 4h14a1 1 0 011 1v8a1 1 0 01-1 1h-4l-3 3-3-3H3a1 1 0 01-1-1V5a1 1 0 011-1z" />
  </svg>
);
