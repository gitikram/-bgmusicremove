/** Hero graphic mirroring the product concept: mixed input -> AI -> kept vocals / removed music. */

export default function HeroDiagram() {
  return (
    <svg viewBox="0 0 680 210" fill="none" className="mx-auto w-full max-w-3xl" role="img" aria-label="Mixed voice and music go into the AI; clean vocals come out, music is removed">
      {/* Input: overlapping voice + music waves */}
      <text x="24" y="196" fill="#a1a1aa" fontSize="11" letterSpacing="2" fontFamily="ui-sans-serif, system-ui">
        INPUT — VOICE + MUSIC
      </text>
      <path
        d="M24 96 q16 -46 32 0 t32 0 t32 0 t32 0 t32 0 t32 0"
        stroke="#e4e4e7"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      <path
        d="M24 122 q16 -22 32 0 t32 0 t32 0 t32 0 t32 0 t32 0"
        stroke="#f43f5e"
        strokeWidth="2.5"
        strokeLinecap="round"
        opacity="0.9"
      />

      {/* Connector into the AI chip */}
      <line x1="220" y1="108" x2="258" y2="108" stroke="#52525b" strokeWidth="2" />

      {/* AI chip */}
      <rect x="258" y="76" width="96" height="64" rx="16" fill="#18181b" stroke="#e4e4e7" strokeWidth="2.5" />
      <circle cx="276" cy="94" r="3" fill="#f43f5e" />
      <circle cx="336" cy="94" r="3" fill="#e4e4e7" />
      <circle cx="276" cy="122" r="3" fill="#e4e4e7" />
      <circle cx="336" cy="122" r="3" fill="#f43f5e" />
      <text x="306" y="114" fill="#fafafa" fontSize="18" fontWeight="700" textAnchor="middle" fontFamily="ui-sans-serif, system-ui">
        AI
      </text>

      {/* Connectors out of the chip */}
      <path d="M354 96 C 380 96 384 52 410 52" stroke="#f43f5e" strokeWidth="2" />
      <path d="M354 120 C 380 120 384 158 410 158" stroke="#52525b" strokeWidth="2" strokeDasharray="4 5" />

      {/* Voice kept card */}
      <rect x="410" y="22" width="246" height="60" rx="12" fill="#fff1f2" fillOpacity="0.08" stroke="#f43f5e" strokeOpacity="0.35" />
      <text x="424" y="42" fill="#fda4af" fontSize="11" letterSpacing="2" fontFamily="ui-sans-serif, system-ui">
        VOICE — KEPT
      </text>
      <path
        d="M424 64 q12 -26 24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0"
        stroke="#be123c"
        strokeWidth="3"
        strokeLinecap="round"
      />

      {/* Music removed card */}
      <rect x="410" y="128" width="246" height="60" rx="12" fill="#fafafa" fillOpacity="0.04" stroke="#3f3f46" />
      <text x="424" y="148" fill="#a1a1aa" fontSize="11" letterSpacing="2" fontFamily="ui-sans-serif, system-ui">
        MUSIC — REMOVED
      </text>
      <path
        d="M424 170 q12 -10 24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0"
        stroke="#71717a"
        strokeWidth="2"
        strokeDasharray="5 5"
        strokeLinecap="round"
      />
    </svg>
  )
}
