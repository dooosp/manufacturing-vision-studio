interface PartPreviewProps {
  variant: "reference" | "inspection";
  showOverlay: boolean;
  imageUrl?: string;
  alt: string;
}

export function PartPreview({ variant, showOverlay, imageUrl, alt }: PartPreviewProps) {
  if (imageUrl) {
    return (
      <div className="part-preview image-preview">
        <img alt={alt} src={imageUrl} />
        {variant === "inspection" && showOverlay ? <div className="mask-overlay" aria-hidden="true" /> : null}
      </div>
    );
  }

  return (
    <div className="part-preview" role="img" aria-label={alt}>
      <svg viewBox="0 0 700 480" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <defs>
          <linearGradient id={`metal-${variant}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#e8edf0" />
            <stop offset=".32" stopColor="#aeb9c0" />
            <stop offset=".62" stopColor="#dce2e5" />
            <stop offset="1" stopColor="#89959c" />
          </linearGradient>
          <linearGradient id={`edge-${variant}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#75838b" />
            <stop offset="1" stopColor="#49545a" />
          </linearGradient>
          <filter id={`shadow-${variant}`} x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy="18" stdDeviation="16" floodColor="#000" floodOpacity=".38" />
          </filter>
          <filter id={`glow-${variant}`} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="12" />
          </filter>
          <pattern id={`grid-${variant}`} width="30" height="30" patternUnits="userSpaceOnUse">
            <path d="M30 0H0v30" fill="none" stroke="#72808a" strokeWidth=".6" opacity=".12" />
          </pattern>
        </defs>

        <rect width="700" height="480" fill="#121b23" />
        <rect width="700" height="480" fill={`url(#grid-${variant})`} />
        <ellipse cx="350" cy="390" rx="235" ry="35" fill="#05090c" opacity=".48" />

        <g filter={`url(#shadow-${variant})`} transform="translate(118 72)">
          <path
            d="M52 56h343c28 0 51 23 51 51v208c0 28-23 51-51 51H52c-28 0-51-23-51-51V107c0-28 23-51 51-51Z"
            fill={`url(#edge-${variant})`}
          />
          <path
            d="M52 35h343c28 0 51 23 51 51v208c0 28-23 51-51 51H52c-28 0-51-23-51-51V86c0-28 23-51 51-51Z"
            fill={`url(#metal-${variant})`}
            stroke="#f5f8f9"
            strokeOpacity=".55"
          />
          <path d="M224 35v310" stroke="#748188" strokeWidth="1" opacity=".45" />
          <path d="M1 190h445" stroke="#748188" strokeWidth="1" opacity=".35" />
          <path d="M72 35c-12 63-10 247 0 310" stroke="#fff" strokeWidth="7" opacity=".12" />

          {[ [94,112], [350,112], [94,268], [350,268] ].map(([cx, cy]) => (
            <g key={`${cx}-${cy}`}>
              <circle cx={cx} cy={cy} r="35" fill="#69767d" stroke="#f4f7f8" strokeOpacity=".52" />
              <circle cx={cx} cy={cy} r="22" fill="#172027" />
              <circle cx={cx - 5} cy={cy - 6} r="6" fill="#2f3e47" />
            </g>
          ))}

          <rect x="169" y="116" width="110" height="155" rx="23" fill="#748187" stroke="#f7f9fa" strokeOpacity=".4" />
          <rect x="186" y="133" width="76" height="121" rx="15" fill="#1b252c" />
          <path d="M196 143h56" stroke="#3b4850" strokeWidth="3" />

          {variant === "inspection" ? (
            <g>
              <path d="M307 241c17-20 45-22 62-5 14 14 14 34 4 48-14 20-46 21-65 3-13-13-12-31-1-46Z" fill="#51464a" opacity=".55" />
              <path d="m310 260 13-12 12 11 13-17 17 22" fill="none" stroke="#22292d" strokeWidth="5" strokeLinecap="round" />
            </g>
          ) : null}
        </g>

        {variant === "inspection" && showOverlay ? (
          <g>
            <ellipse cx="453" cy="331" rx="67" ry="54" fill="#ff4f4f" opacity=".28" filter={`url(#glow-${variant})`} />
            <path d="M405 307c18-25 57-32 84-12 28 22 31 59 8 84-24 25-67 23-88-2-17-20-19-48-4-70Z" fill="#ff5d54" opacity=".28" stroke="#ff7b70" strokeWidth="3" strokeDasharray="8 7" />
            <path d="M502 284h68" stroke="#ff8e84" strokeWidth="2" />
            <rect x="535" y="245" width="132" height="40" rx="6" fill="#20191a" stroke="#ff6e64" />
            <text x="551" y="270" fill="#ffb3ad" fontSize="14" fontFamily="ui-monospace, monospace">edge_2 · 0.84</text>
          </g>
        ) : null}

        <g transform="translate(26 430)">
          <path d="M0 0h92" stroke="#9faab0" strokeWidth="2" />
          <path d="M0-5v10M92-5v10" stroke="#9faab0" strokeWidth="2" />
          <text y="24" fill="#85939b" fontSize="12" fontFamily="ui-monospace, monospace">50 mm</text>
        </g>
      </svg>
    </div>
  );
}

