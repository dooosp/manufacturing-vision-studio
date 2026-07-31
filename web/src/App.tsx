import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { getCopy } from "./copy";
import { AppHeader } from "./components/AppHeader";
import { CaseRail } from "./components/CaseRail";
import { DispositionPanel } from "./components/DispositionPanel";
import { EvidencePanel } from "./components/EvidencePanel";
import { InspectionWorkspace } from "./components/InspectionWorkspace";
import type { Decision, InspectionCase, Locale } from "./types";

type Operation = "loading" | "create" | "upload" | "analyze" | "disposition" | "export" | null;

function caseIdentity(item: InspectionCase): string {
  return item.id || item.case_id || "";
}

export function App() {
  const [locale, setLocale] = useState<Locale>("en");
  const [cases, setCases] = useState<InspectionCase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [operation, setOperation] = useState<Operation>("loading");
  const [connected, setConnected] = useState(false);
  const [showOverlay, setShowOverlay] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const started = useRef(false);
  const copy = getCopy(locale);

  const selectedCase = useMemo(
    () => cases.find((item) => caseIdentity(item) === selectedId) ?? cases[0] ?? null,
    [cases, selectedId],
  );

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    async function load() {
      try {
        const [health, existingCases] = await Promise.all([api.health(), api.listCases()]);
        setConnected(health.status === "ok" || health.status === "healthy");
        let nextCases = existingCases;
        if (nextCases.length === 0) {
          const demo = await api.createDemo();
          nextCases = [demo];
        }
        setCases(nextCases);
        setSelectedId(nextCases[0] ? caseIdentity(nextCases[0]) : null);
      } catch (cause) {
        setConnected(false);
        setError(cause instanceof Error ? cause.message : "Unable to load the local API");
      } finally {
        setOperation(null);
      }
    }

    void load();
  }, []);

  function replaceCase(nextCase: InspectionCase) {
    const id = caseIdentity(nextCase);
    setCases((current) => {
      const exists = current.some((item) => caseIdentity(item) === id);
      return exists
        ? current.map((item) => (caseIdentity(item) === id ? nextCase : item))
        : [nextCase, ...current];
    });
    setSelectedId(id);
    setConnected(true);
  }

  async function perform<T>(nextOperation: Exclude<Operation, null>, action: () => Promise<T>): Promise<T | null> {
    setOperation(nextOperation);
    setError(null);
    setNotice(null);
    try {
      return await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unknown local operation failure");
      return null;
    } finally {
      setOperation(null);
    }
  }

  async function createCase(partId: string, revision: string) {
    const created = await perform("create", () => api.createCase(partId, revision));
    if (created) replaceCase(created);
  }

  async function createDemo() {
    const demo = await perform("create", api.createDemo);
    if (demo) replaceCase(demo);
  }

  async function uploadReference(file: File) {
    if (!selectedCase) return;
    const updated = await perform("upload", () =>
      api.uploadReference(caseIdentity(selectedCase), selectedCase.case_revision ?? 1, file),
    );
    if (updated) replaceCase(updated);
  }

  async function uploadInspection(file: File) {
    if (!selectedCase) return;
    const updated = await perform("upload", () =>
      api.uploadInspection(caseIdentity(selectedCase), selectedCase.case_revision ?? 1, file),
    );
    if (updated) replaceCase(updated);
  }

  async function analyze() {
    if (!selectedCase) return;
    const updated = await perform("analyze", () =>
      api.analyze(caseIdentity(selectedCase), selectedCase.case_revision ?? 1),
    );
    if (updated) {
      replaceCase(updated);
      setShowOverlay(true);
    }
  }

  async function recordDisposition(decision: Decision, reviewer: string, note: string) {
    if (!selectedCase) return;
    const updated = await perform("disposition", () =>
      api.disposition(
        caseIdentity(selectedCase),
        selectedCase.case_revision ?? 1,
        selectedCase.analysis?.analysis_id ?? "",
        decision,
        reviewer,
        note,
      ),
    );
    if (updated) replaceCase(updated);
  }

  async function exportAndVerify() {
    if (!selectedCase) return;
    const exported = await perform("export", async () => {
      const bundle = await api.exportEvidence(
        caseIdentity(selectedCase),
        selectedCase.case_revision ?? 1,
      );
      const verification = await api.verifyEvidence(bundle.download_url);
      if (!verification.valid) {
        throw new Error(verification.errors?.join("; ") || "Bundle verification failed closed");
      }
      return { bundle, verification };
    });

    if (exported) {
      const refreshed = await perform("loading", () => api.getCase(caseIdentity(selectedCase)));
      if (refreshed) replaceCase(refreshed);
      setNotice(`${copy.captured} · SHA-256 ${exported.bundle.bundle_sha256.slice(0, 16)}…`);
    }
  }

  const busy = operation !== null;

  return (
    <div className="app-shell">
      <AppHeader
        locale={locale}
        copy={copy}
        connected={connected}
        onLocaleChange={setLocale}
      />

      <div className="app-layout">
        <CaseRail
          cases={cases}
          selectedId={selectedId}
          copy={copy}
          busy={busy}
          onSelect={setSelectedId}
          onCreate={createCase}
          onCreateDemo={createDemo}
        />

        <main id="main-content" className="main-content">
          {error ? (
            <div className="alert alert-error" role="alert">
              <span aria-hidden="true">!</span>
              <div><strong>{copy.safeFailure}</strong><p>{error}</p></div>
              <button type="button" aria-label={copy.dismissError} onClick={() => setError(null)}>×</button>
            </div>
          ) : null}
          {notice ? (
            <div className="alert alert-success" role="status">
              <span aria-hidden="true">✓</span>
              <p>{notice}</p>
              <button type="button" aria-label={copy.dismissNotice} onClick={() => setNotice(null)}>×</button>
            </div>
          ) : null}

          {selectedCase ? (
            <div className="workspace-grid">
              <InspectionWorkspace
                inspectionCase={selectedCase}
                copy={copy}
                busy={busy}
                showOverlay={showOverlay}
                onOverlayChange={setShowOverlay}
                onAnalyze={analyze}
                onUploadReference={uploadReference}
                onUploadInspection={uploadInspection}
              />
              <div className="side-column">
                <EvidencePanel inspectionCase={selectedCase} copy={copy} />
                <DispositionPanel
                  key={caseIdentity(selectedCase)}
                  current={selectedCase.disposition}
                  copy={copy}
                  disabled={busy || !selectedCase.analysis}
                  exporting={operation === "export"}
                  onSubmit={recordDisposition}
                  onExport={exportAndVerify}
                />
              </div>
            </div>
          ) : (
            <section className="empty-workspace">
              <div className="empty-workspace-mark" aria-hidden="true">◇</div>
              <h2>{copy.openCase}</h2>
              <p>{copy.selectCase}</p>
              <button className="button button-primary" type="button" disabled={busy} onClick={() => void createDemo()}>
                {copy.loadDemo}
              </button>
            </section>
          )}
        </main>
      </div>

      <footer className="app-footer">
        <span>{copy.footerTarget}</span>
        <span>{copy.footerContract}</span>
        <span>{copy.footerBoundary}</span>
      </footer>
    </div>
  );
}
