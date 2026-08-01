import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { getCopy } from "./copy";
import { AppHeader } from "./components/AppHeader";
import { CaseRail } from "./components/CaseRail";
import { DispositionPanel } from "./components/DispositionPanel";
import { EvidencePanel } from "./components/EvidencePanel";
import {
  EvaluationWorkspace,
  type EvaluationLoadState,
} from "./components/EvaluationWorkspace";
import { InspectionWorkspace } from "./components/InspectionWorkspace";
import type {
  AppSurface,
  Decision,
  E1EvaluationSnapshot,
  EvaluationProfile,
  InspectionCase,
  Locale,
} from "./types";

type Operation = "loading" | "create" | "upload" | "analyze" | "disposition" | "export" | null;

function caseIdentity(item: InspectionCase): string {
  return item.id || item.case_id || "";
}

export function App() {
  const [locale, setLocale] = useState<Locale>("en");
  const [activeSurface, setActiveSurface] = useState<AppSurface>("inspection");
  const [cases, setCases] = useState<InspectionCase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [operation, setOperation] = useState<Operation>("loading");
  const [connected, setConnected] = useState(false);
  const [showOverlay, setShowOverlay] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<E1EvaluationSnapshot | null>(null);
  const [evaluationProfile, setEvaluationProfile] = useState<EvaluationProfile>("mini");
  const [evaluationState, setEvaluationState] = useState<EvaluationLoadState>("idle");
  const [evaluationError, setEvaluationError] = useState<string | null>(null);
  const started = useRef(false);
  const evaluationRequestId = useRef(0);
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
        setCases(existingCases);
        setSelectedId(existingCases[0] ? caseIdentity(existingCases[0]) : null);
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

  async function loadEvaluation(profile: EvaluationProfile = evaluationProfile) {
    const requestId = evaluationRequestId.current + 1;
    evaluationRequestId.current = requestId;
    setEvaluationProfile(profile);
    setEvaluationState("loading");
    setEvaluationError(null);
    try {
      const latest = await api.getLatestEvaluation(profile);
      if (requestId !== evaluationRequestId.current) return;
      setEvaluation(latest);
      setEvaluationState(latest ? "ready" : "empty");
    } catch (cause) {
      if (requestId !== evaluationRequestId.current) return;
      setEvaluation(null);
      if (cause instanceof ApiError && cause.status === 404) {
        setEvaluationState("empty");
        return;
      }
      setEvaluationError(cause instanceof Error ? cause.message : "Unable to read E1 evaluation");
      setEvaluationState("error");
    }
  }

  function selectSurface(surface: AppSurface) {
    setActiveSurface(surface);
    if (surface === "evaluation" && evaluationState === "idle") {
      void loadEvaluation();
    }
  }

  const busy = operation !== null;

  return (
    <div className="app-shell">
      <AppHeader
        locale={locale}
        copy={copy}
        connected={connected}
        activeSurface={activeSurface}
        onLocaleChange={setLocale}
        onSurfaceChange={selectSurface}
      />

      <>
        <div
          id="inspection-panel"
          className="app-layout"
          role="tabpanel"
          aria-labelledby="inspection-tab"
          hidden={activeSurface !== "inspection"}
        >
          <CaseRail
            cases={cases}
            selectedId={selectedId}
            copy={copy}
            busy={busy}
            onSelect={setSelectedId}
            onCreate={createCase}
            onCreateDemo={createDemo}
          />

          <main
            id={activeSurface === "inspection" ? "main-content" : "inspection-main-content"}
            className="main-content"
          >
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
        <div
          id="evaluation-panel"
          role="tabpanel"
          aria-labelledby="evaluation-tab"
          hidden={activeSurface !== "evaluation"}
        >
          <main
            id={activeSurface === "evaluation" ? "main-content" : "evaluation-main-content"}
            className="evaluation-main"
          >
            <EvaluationWorkspace
              copy={copy}
              locale={locale}
              snapshot={evaluation}
              profile={evaluationProfile}
              state={evaluationState}
              error={evaluationError}
              onRefresh={loadEvaluation}
              onProfileChange={loadEvaluation}
            />
          </main>
        </div>
      </>

      <footer className="app-footer">
        <span>{copy.footerTarget}</span>
        <span>{copy.footerContract}</span>
        <span>{copy.footerBoundary}</span>
      </footer>
    </div>
  );
}
