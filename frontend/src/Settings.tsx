import { useEffect, useState } from "react";
import { Monitor, HardDrive, Power, FileText, ShieldCheck } from "lucide-react";
import { api, bytes, patch, post } from "./api";
import type { Snapshot } from "./types";
export function Settings({
  snapshot,
  refresh,
  notify,
}: {
  snapshot: Snapshot;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
}) {
  const [settings, setSettings] = useState({
    low_vram: false,
    unload_after_job: false,
  });
  const [logs, setLogs] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<typeof settings>("/settings")
      .then(setSettings)
      .catch((e) => setError(e.message));
  }, []);
  const save = async (values: object) => {
    setBusy(true);
    try {
      setSettings(await patch("/settings", values));
      notify("Runtime settings saved");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const release = async () => {
    setBusy(true);
    try {
      await post("/runtime/release");
      await refresh();
      notify("GPU worker stopped");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const active = snapshot.jobs.some((j) =>
    ["queued", "running"].includes(j.status),
  );
  const hw = snapshot.status?.hardware;
  return (
    <div className="page settings-page">
      <header className="page-head">
        <div>
          <h1>Settings</h1>
          <p>A studio that fits your machine.</p>
        </div>
      </header>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <section className="surface settings-section">
        <h2>
          <Monitor size={21} />
          Hardware & runtime
        </h2>
        <dl className="detail-list">
          <div>
            <dt>GPU</dt>
            <dd>{hw?.gpu_name || "No NVIDIA GPU detected"}</dd>
          </div>
          <div>
            <dt>GPU memory</dt>
            <dd>
              {hw
                ? `${(hw.gpu_used_mib / 1024).toFixed(1)} / ${(hw.gpu_total_mib / 1024).toFixed(1)} GB`
                : "—"}
            </dd>
          </div>
          <div>
            <dt>Worker</dt>
            <dd>
              {snapshot.status?.active_model
                ? snapshot.models.find(
                    (m) => m.id === snapshot.status?.active_model,
                  )?.name
                : "No model loaded"}{" "}
              · {snapshot.status?.runtime_phase || "Idle"}
            </dd>
          </div>
        </dl>
        <button
          className="secondary"
          onClick={() => void release()}
          disabled={busy || active || !snapshot.status?.active_model}
        >
          <Power size={16} />
          Release GPU memory
        </button>
        <p className="muted-text">
          Models switch automatically. The previous worker stops before the next
          one loads.
        </p>
      </section>
      <section className="surface settings-section">
        <h2>Memory preferences</h2>
        <label className="setting-toggle">
          <span>
            <strong>Low-VRAM mode for Qwen</strong>
            <small>
              Offload more work to system RAM. Generation may take longer.
            </small>
          </span>
          <input
            type="checkbox"
            checked={settings.low_vram}
            disabled={busy || active}
            onChange={(e) => void save({ low_vram: e.target.checked })}
          />
        </label>
        <label className="setting-toggle">
          <span>
            <strong>Unload after each job</strong>
            <small>
              Free GPU memory after a batch completes. The next job reloads its
              model.
            </small>
          </span>
          <input
            type="checkbox"
            checked={settings.unload_after_job}
            disabled={busy || active}
            onChange={(e) => void save({ unload_after_job: e.target.checked })}
          />
        </label>
      </section>
      <section className="surface settings-section">
        <h2>
          <HardDrive size={20} />
          Storage
        </h2>
        <dl className="detail-list">
          <div>
            <dt>Projects and images</dt>
            <dd>
              <code>{snapshot.status?.data_path}</code>
            </dd>
          </div>
          <div>
            <dt>Available disk space</dt>
            <dd>{bytes(hw?.disk_free_bytes || 0)}</dd>
          </div>
        </dl>
        <p className="muted-text">
          Back up the data folder to preserve projects, prompts, reference
          images and generated files. Archived projects and trashed images
          remain recoverable.
        </p>
      </section>
      <section className="surface settings-section">
        <h2>
          <ShieldCheck size={20} />
          Local by design
        </h2>
        <p>
          Generation runs on your GPU. No account, usage credits or hosted
          inference service is required. Installation and verification contact
          GitHub and Hugging Face to fetch runtimes, weights and checksums.
          Model licenses are listed in the library.
        </p>
      </section>
      <section className="surface settings-section">
        <h2>
          <FileText size={20} />
          Diagnostics
        </h2>
        <button
          className="secondary"
          onClick={() => {
            api<Record<string, string>>("/runtime/logs")
              .then(setLogs)
              .catch((e) => setError(e.message));
          }}
        >
          Read runtime logs
        </button>
        {logs ? (
          Object.entries(logs).length ? (
            Object.entries(logs).map(([name, content]) => (
              <details key={name}>
                <summary>{name}</summary>
                <pre className="runtime-log">{content || "No output yet."}</pre>
              </details>
            ))
          ) : (
            <p className="muted-text">No workers have started yet.</p>
          )
        ) : null}
      </section>
    </div>
  );
}
