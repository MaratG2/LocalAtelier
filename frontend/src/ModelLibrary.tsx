import { useState } from "react";
import {
  Download,
  ShieldCheck,
  Trash2,
  Folder,
  RefreshCw,
  Check,
  LoaderCircle,
  ChevronDown,
  HardDrive,
  Layers,
} from "lucide-react";
import { api, bytes, date, post } from "./api";
import { Modal, ExternalLink } from "./ui";
import type { Model, Snapshot } from "./types";

export function ModelLibrary({
  snapshot,
  refresh,
  notify,
}: {
  snapshot: Snapshot;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [dialog, setDialog] = useState<{
    model: Model;
    action: "install" | "remove";
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string | null>(null);
  const action = async (model: Model, type: string) => {
    setBusy(true);
    setError("");
    try {
      if (type === "remove")
        await api(`/models/${model.id}`, {
          method: "DELETE",
          body: JSON.stringify({ confirmation: model.name }),
        });
      else await post(`/models/${model.id}/${type}`);
      setDialog(null);
      await refresh();
      notify(
        type === "remove"
          ? "Model removed"
          : type === "verify"
            ? "Verification started"
            : "Installation started",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const open = (model: Model, action: "install" | "remove") => {
    setError("");
    setDialog({ model, action });
  };
  const models = snapshot.models.filter(
    (m) => filter === "all" || m.status === "installed",
  );
  return (
    <div className="page models-page">
      <header className="page-head">
        <div>
          <h1>Model library</h1>
          <p>Your models. Your hardware. Choose what belongs in your studio.</p>
        </div>
        <button className="secondary" onClick={() => void refresh()}>
          <RefreshCw size={18} />
          Refresh
        </button>
      </header>
      <div className="library-summary">
        <div>
          <HardDrive size={20} />
          <strong>
            {bytes(snapshot.models.reduce((n, m) => n + m.size_bytes, 0))}
          </strong>
          <span>model weights installed</span>
        </div>
        <div>
          <span>
            {bytes(snapshot.status?.hardware.disk_free_bytes || 0)} free on disk
          </span>
        </div>
      </div>
      <div className="toolbar library-toolbar">
        <div className="segmented">
          <button
            className={filter === "all" ? "active" : ""}
            onClick={() => setFilter("all")}
          >
            All models <span>{snapshot.models.length}</span>
          </button>
          <button
            className={filter === "installed" ? "active" : ""}
            onClick={() => setFilter("installed")}
          >
            Installed{" "}
            <span>
              {snapshot.models.filter((m) => m.status === "installed").length}
            </span>
          </button>
        </div>
        <span className="muted-text">Image models · 16 GB profiles</span>
      </div>
      {error && !dialog ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <div className="model-library-list">
        {models.map((m) => (
          <article className="model-card" key={m.id}>
            <div className="model-card-top">
              <div
                className={`model-avatar ${m.family === "HiDream" ? "earth" : ""}`}
              >
                {m.family === "Qwen" ? "Q" : "H"}
              </div>
              <div className="model-heading">
                <div>
                  <h2>{m.name}</h2>
                  <span
                    className={`badge ${m.status === "installed" ? "green" : "muted"}`}
                  >
                    {m.busy
                      ? "Working"
                      : m.status === "installed"
                        ? "Installed"
                        : m.status === "incomplete"
                          ? "Incomplete"
                          : "Available"}
                  </span>
                </div>
                <p>{m.description}</p>
              </div>
            </div>
            <div className="model-facts">
              <span>
                <strong>{m.precision}</strong> precision
              </span>
              <span>
                <strong>{m.download_gb} GB</strong> weights
              </span>
              <span>
                <strong>{m.max_references}</strong> references
              </span>
              <span>
                <strong>{m.transparent ? "Native RGBA" : "RGB"}</strong> output
              </span>
            </div>
            <div className="model-details">
              <ExternalLink href={`https://huggingface.co/${m.hub_repo}`}>
                Model source
              </ExternalLink>
              <ExternalLink href={m.license_url}>{m.license}</ExternalLink>
              {m.verified ? (
                <span className="verified">
                  <ShieldCheck size={15} />
                  Verified {date(m.verified)}
                </span>
              ) : (
                <span className="muted-text">
                  {m.status === "installed"
                    ? "Not verified in this studio"
                    : "Verify after installation"}
                </span>
              )}
            </div>
            {m.runtime_path ? (
              <div className="installation-path">
                <Folder size={14} />
                <code>{m.runtime_path}</code>
                <span>Stored inside Local Atelier</span>
              </div>
            ) : null}
            {m.operation ? (
              <div
                className={`operation ${m.operation.status === "error" ? "failed" : ""}`}
              >
                <div>
                  <span>
                    {m.operation.status === "running" ? (
                      <LoaderCircle size={15} className="spin" />
                    ) : m.operation.status === "complete" ? (
                      <Check size={15} />
                    ) : null}
                    {m.operation.phase}
                  </span>
                  {m.operation.status === "running" &&
                  m.operation.progress !== null ? (
                    <strong>{m.operation.progress}%</strong>
                  ) : null}
                  <button
                    className="text-link"
                    onClick={() => setLogs(logs === m.id ? null : m.id)}
                  >
                    Details
                    <ChevronDown size={14} />
                  </button>
                </div>
                {m.operation.status === "running" ? (
                  <div
                    className={`progress ${m.operation.progress === null ? "indeterminate" : ""}`}
                  >
                    <i style={{ width: `${m.operation.progress ?? 30}%` }} />
                  </div>
                ) : null}
                {m.operation.error ? (
                  <p role="alert">{m.operation.error}</p>
                ) : null}
                {logs === m.id ? (
                  <pre>
                    {m.operation.logs.join("\n") ||
                      "Reading files and checking them against the pinned publisher revision."}
                  </pre>
                ) : null}
              </div>
            ) : null}
            <footer className="model-actions">
              {m.status === "installed" ? (
                <>
                  <button
                    className="secondary"
                    disabled={m.busy || m.in_use || busy}
                    onClick={() => void action(m, "verify")}
                  >
                    <ShieldCheck size={17} />
                    Verify files
                  </button>
                  <button
                    className="quiet danger"
                    disabled={m.busy || m.in_use || busy}
                    onClick={() => open(m, "remove")}
                  >
                    <Trash2 size={16} /> Delete model
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="primary"
                    disabled={m.busy || busy}
                    onClick={() => open(m, "install")}
                  >
                    <Download size={17} />
                    {m.status === "incomplete"
                      ? "Resume install"
                      : "Install model"}
                  </button>
                  {m.source ? (
                    <button
                      className="quiet danger"
                      onClick={() => open(m, "remove")}
                      disabled={m.busy || busy}
                    >
                      <Trash2 size={16} />
                      Remove partial files
                    </button>
                  ) : null}
                </>
              )}
              <span>
                {m.in_use
                  ? "In generation queue"
                  : snapshot.status?.active_model === m.id
                    ? "Loaded on GPU"
                    : ""}
              </span>
            </footer>
          </article>
        ))}
      </div>
      <div className="library-note">
        <Layers size={21} />
        <div>
          <strong>Room to grow</strong>
          <p>
            More local models and creative tools can join the same projects and
            asset library. 3D, video and audio adapters are planned.
          </p>
        </div>
      </div>
      {dialog ? (
        <Modal
          title={
            dialog.action === "install"
              ? `Install ${dialog.model.name}`
              : `Delete ${dialog.model.name}`
          }
          onClose={() => !busy && setDialog(null)}
        >
          <div className="dialog-body form-stack">
            {dialog.action === "install" ? (
              <>
                <p>
                  This installs approximately{" "}
                  <strong>{dialog.model.download_gb} GB</strong> of weights plus
                  an isolated GPU runtime, inside Local Atelier's models folder.
                </p>
                <p>
                  Requires Windows, uv and an NVIDIA GPU. You can keep browsing
                  while installation runs.
                </p>
                <ExternalLink href={dialog.model.license_url}>
                  Read the model's {dialog.model.license}
                </ExternalLink>
              </>
            ) : (
              <p>
                This permanently deletes the runtime and downloaded weights
                owned by Local Atelier ({bytes(dialog.model.size_bytes)}).
                Project images remain in your library. You can install the model
                again later.
              </p>
            )}
            {error ? (
              <p className="error" role="alert">
                {error}
              </p>
            ) : null}
            <div className="dialog-actions">
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setDialog(null)}
              >
                Cancel
              </button>
              <button
                className={
                  dialog.action === "remove" ? "danger-button" : "primary"
                }
                disabled={busy}
                onClick={() => void action(dialog.model, dialog.action)}
              >
                {busy
                  ? "Working…"
                  : dialog.action === "install"
                    ? "Install model"
                    : "Delete model"}
              </button>
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
