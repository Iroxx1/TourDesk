// The TourDesk app icon (same artwork as public/icons/tourdesk.svg), used as Start button.
import { useId } from "react";

export function Logo({ size = 24, className }: { size?: number; className?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const bg = `tdbg${id}`;
  const shine = `tdsh${id}`;
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 64 64" aria-hidden focusable="false">
      <defs>
        <linearGradient id={bg} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1c8dff" />
          <stop offset="0.55" stopColor="#5a46f5" />
          <stop offset="1" stopColor="#b83ad6" />
        </linearGradient>
        <linearGradient id={shine} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.38" />
          <stop offset="0.55" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="15" fill={`url(#${bg})`} />
      <rect x="2" y="2" width="60" height="60" rx="15" fill={`url(#${shine})`} />
      <path
        d="M16 17 H48 a4 4 0 0 1 4 4 V28 a4 4 0 0 0 0 8 V43 a4 4 0 0 1 -4 4 H16 a4 4 0 0 1 -4 -4 V36 a4 4 0 0 0 0 -8 V21 a4 4 0 0 1 4 -4 Z"
        fill="#ffffff"
      />
      <path d="M40.5 20.5 V43.5" stroke="#5a46f5" strokeOpacity="0.55" strokeWidth="2" strokeLinecap="round" strokeDasharray="0.1 4.2" />
      <rect x="19" y="29" width="3.4" height="10" rx="1.7" fill={`url(#${bg})`} />
      <rect x="25" y="23.5" width="3.4" height="15.5" rx="1.7" fill={`url(#${bg})`} />
      <rect x="31" y="26.5" width="3.4" height="12.5" rx="1.7" fill={`url(#${bg})`} />
      <circle cx="46.5" cy="32" r="2.6" fill={`url(#${bg})`} />
    </svg>
  );
}
