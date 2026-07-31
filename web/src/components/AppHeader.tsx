import { useRef } from "react";
import type { KeyboardEvent } from "react";
import { BrandMark } from "./BrandMark";
import type { Copy } from "../copy";
import type { AppSurface, Locale } from "../types";

interface AppHeaderProps {
  locale: Locale;
  copy: Copy;
  connected: boolean;
  activeSurface: AppSurface;
  onLocaleChange: (locale: Locale) => void;
  onSurfaceChange: (surface: AppSurface) => void;
}

export function AppHeader({
  locale,
  copy,
  connected,
  activeSurface,
  onLocaleChange,
  onSurfaceChange,
}: AppHeaderProps) {
  const inspectionTab = useRef<HTMLButtonElement>(null);
  const evaluationTab = useRef<HTMLButtonElement>(null);

  function activateSurface(surface: AppSurface) {
    onSurfaceChange(surface);
    requestAnimationFrame(() => {
      (surface === "inspection" ? inspectionTab : evaluationTab).current?.focus();
    });
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") {
      activateSurface("inspection");
      return;
    }
    if (event.key === "End") {
      activateSurface("evaluation");
      return;
    }
    activateSurface(activeSurface === "inspection" ? "evaluation" : "inspection");
  }

  return (
    <header className="app-header">
      <div className="brand-lockup">
        <BrandMark />
        <div>
          <p className="eyebrow">{copy.productKicker}</p>
          <h1>Manufacturing Vision Studio</h1>
        </div>
      </div>

      <div className="surface-navigation" role="tablist" aria-label={copy.surfaceNavigation}>
        <button
          ref={inspectionTab}
          id="inspection-tab"
          role="tab"
          type="button"
          aria-controls="inspection-panel"
          aria-selected={activeSurface === "inspection"}
          tabIndex={activeSurface === "inspection" ? 0 : -1}
          className={activeSurface === "inspection" ? "is-active" : ""}
          onClick={() => onSurfaceChange("inspection")}
          onKeyDown={handleTabKeyDown}
        >
          {copy.inspectionTab}
        </button>
        <button
          ref={evaluationTab}
          id="evaluation-tab"
          role="tab"
          type="button"
          aria-controls="evaluation-panel"
          aria-selected={activeSurface === "evaluation"}
          tabIndex={activeSurface === "evaluation" ? 0 : -1}
          className={activeSurface === "evaluation" ? "is-active" : ""}
          onClick={() => onSurfaceChange("evaluation")}
          onKeyDown={handleTabKeyDown}
        >
          {copy.evaluationTab}
        </button>
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
