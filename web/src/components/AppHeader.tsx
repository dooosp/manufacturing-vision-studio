import { BrandMark } from "./BrandMark";
import type { Copy } from "../copy";
import type { Locale } from "../types";

interface AppHeaderProps {
  locale: Locale;
  copy: Copy;
  connected: boolean;
  onLocaleChange: (locale: Locale) => void;
}

export function AppHeader({ locale, copy, connected, onLocaleChange }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="brand-lockup">
        <BrandMark />
        <div>
          <p className="eyebrow">Industrial evidence workbench</p>
          <h1>Manufacturing Vision Studio</h1>
        </div>
      </div>

      <div className="header-controls">
        <span className="mode-badge"><span className="mode-dot" />{copy.demoMode}</span>
        <span className="local-badge">{copy.localOnly}</span>
        <span className={`connection-state ${connected ? "is-connected" : "is-offline"}`}>
          <span className="connection-dot" />
          {connected ? copy.connected : copy.disconnected}
        </span>
        <div className="language-switch" role="group" aria-label={copy.language}>
          <button
            className={locale === "en" ? "is-active" : ""}
            type="button"
            aria-pressed={locale === "en"}
            onClick={() => onLocaleChange("en")}
          >
            EN
          </button>
          <button
            className={locale === "ko" ? "is-active" : ""}
            type="button"
            aria-pressed={locale === "ko"}
            onClick={() => onLocaleChange("ko")}
          >
            한국어
          </button>
        </div>
      </div>
    </header>
  );
}

