import { t, quantity, number } from "./i18n";
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
  const [service, setService] = useState("all");
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
  const serviceModels = snapshot.models.filter(
    (m) => service === "all" || m.service === service,
  );
  const models = serviceModels.filter(
    (m) => filter === "all" || m.status === "installed",
  );
  return (
    <div className="page models-page">
      <header className="page-head">
        <div>
          <h1> {t("Model library")} </h1>
          <p>
            {" "}
            {t(
              "Your models. Your hardware. Choose what belongs in your studio.",
            )}{" "}
          </p>
        </div>
        <button className="secondary" onClick={() => void refresh()}>
          <RefreshCw size={18} /> {t("Refresh")}{" "}
        </button>
      </header>
      <div className="library-summary">
        <div>
          <HardDrive size={20} />
          <strong>
            {" "}
            {t(
              bytes(snapshot.models.reduce((n, m) => n + m.size_bytes, 0)),
            )}{" "}
          </strong>
          <span> {t("model weights installed")} </span>
        </div>
        <div>
          <span>
            {" "}
            {t(bytes(snapshot.status?.hardware.disk_free_bytes || 0))}{" "}
            {t("free on disk")}{" "}
          </span>
        </div>
      </div>
      <div className="toolbar library-toolbar">
        <div className="segmented">
          <button
            className={filter === "all" ? "active" : ""}
            onClick={() => setFilter("all")}
          >
            {" "}
            {t("All models")} <span>{serviceModels.length}</span>
          </button>
          <button
            className={filter === "installed" ? "active" : ""}
            onClick={() => setFilter("installed")}
          >
            {" "}
            {t("Installed")}{" "}
            <span>
              {serviceModels.filter((m) => m.status === "installed").length}
            </span>
          </button>
        </div>
        <select
          aria-label={t("Model service")}
          value={service}
          onChange={(e) => setService(e.target.value)}
        >
          <option value="all"> {t("All services")} </option>
          <option value="images"> {t("Images")} </option>
          <option value="3d"> {t("3D objects")} </option>
          <option value="video"> {t("Video")} </option>
        </select>
      </div>
      {error && !dialog ? (
        <div className="error-banner" role="alert">
          {" "}
          {t(error)}{" "}
        </div>
      ) : null}
      <div className="model-library-list">
        {models.map((m) => (
          <article className="model-card" key={m.id}>
            <div className="model-card-top">
              <div
                className={`model-avatar ${m.family === "HiDream" ? "earth" : ""}`}
              >
                {" "}
                {t(
                  m.family === "Qwen"
                    ? "Q"
                    : m.service === "3d"
                      ? "3D"
                      : m.service === "video"
                        ? "H3"
                        : "H",
                )}{" "}
              </div>
              <div className="model-heading">
                <div>
                  <h2>{m.name}</h2>
                  <span
                    className={`badge ${m.status === "installed" ? "green" : "muted"}`}
                  >
                    {" "}
                    {t(
                      m.busy
                        ? "Working"
                        : m.status === "installed"
                          ? "Installed"
                          : m.status === "incomplete"
                            ? "Incomplete"
                            : "Available",
                    )}{" "}
                  </span>
                </div>
                <p> {t(m.description)} </p>
              </div>
            </div>
            <div className="model-facts">
              <span>
                <strong> {t(m.precision)} </strong> {t("precision")}{" "}
              </span>
              <span>
                <strong>
                  {number(m.download_gb)} {t("GB")}{" "}
                </strong>{" "}
                {t("weights")}{" "}
              </span>
              <span>
                <strong>{quantity(m.max_references, "references")}</strong>{" "}
              </span>
              <span>
                <strong>
                  {" "}
                  {t(
                    m.service === "video"
                      ? "Video + stereo"
                      : m.service === "3d"
                        ? "Mesh + PBR"
                        : m.transparent
                          ? "Native RGBA"
                          : "RGB",
                  )}{" "}
                </strong>{" "}
                {t("output")}{" "}
              </span>
            </div>
            <div className="model-details">
              <ExternalLink href={`https://huggingface.co/${m.hub_repo}`}>
                {" "}
                {t("Model source")}{" "}
              </ExternalLink>
              <ExternalLink href={m.license_url}> {t(m.license)} </ExternalLink>
              {m.verified ? (
                <span className="verified">
                  <ShieldCheck size={15} /> {t("Verified")}{" "}
                  {t(date(m.verified))}{" "}
                </span>
              ) : (
                <span className="muted-text">
                  {" "}
                  {t(
                    m.status === "installed"
                      ? "Not verified in this studio"
                      : "Verify after installation",
                  )}{" "}
                </span>
              )}
            </div>
            {m.runtime_path ? (
              <div className="installation-path">
                <Folder size={14} />
                <code> {t(m.runtime_path)} </code>
                <span> {t("Stored inside Local Atelier")} </span>
              </div>
            ) : null}
            {m.operation ? (
              <div
                className={`operation ${m.operation.status === "error" ? "failed" : ""}`}
              >
                <div>
                  <span>
                    {m.operation.status === t("running") ? (
                      <LoaderCircle size={15} className="spin" />
                    ) : m.operation.status === t("complete") ? (
                      <Check size={15} />
                    ) : null}{" "}
                    {t(m.operation.phase)}{" "}
                  </span>
                  {m.operation.status === t("running") &&
                  m.operation.progress !== null ? (
                    <strong>{m.operation.progress}%</strong>
                  ) : null}
                  <button
                    className="text-link"
                    onClick={() => setLogs(logs === m.id ? null : m.id)}
                  >
                    {" "}
                    {t("Details")} <ChevronDown size={14} />
                  </button>
                </div>
                {m.operation.status === t("running") ? (
                  <div
                    className={`progress ${m.operation.progress === null ? "indeterminate" : ""}`}
                  >
                    <i style={{ width: `${m.operation.progress ?? 30}%` }} />
                  </div>
                ) : null}
                {m.operation.error ? (
                  <p role="alert"> {t(m.operation.error)} </p>
                ) : null}
                {logs === m.id ? (
                  <pre>
                    {" "}
                    {t(
                      m.operation.logs.join("\n") ||
                        "Reading files and checking them against the pinned publisher revision.",
                    )}{" "}
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
                    <ShieldCheck size={17} /> {t("Verify files")}{" "}
                  </button>
                  <button
                    className="quiet danger"
                    disabled={m.busy || m.in_use || busy}
                    onClick={() => open(m, "remove")}
                  >
                    <Trash2 size={16} /> {t("Delete model")}{" "}
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="primary"
                    disabled={m.busy || busy}
                    onClick={() => open(m, "install")}
                  >
                    <Download size={17} />{" "}
                    {t(
                      m.status === "incomplete"
                        ? "Resume install"
                        : "Install model",
                    )}{" "}
                  </button>
                  {m.source ? (
                    <button
                      className="quiet danger"
                      onClick={() => open(m, "remove")}
                      disabled={m.busy || busy}
                    >
                      <Trash2 size={16} /> {t("Remove partial files")}{" "}
                    </button>
                  ) : null}
                </>
              )}
              <span>
                {" "}
                {t(
                  m.in_use
                    ? "In generation queue"
                    : snapshot.status?.active_model === m.id
                      ? "Loaded on GPU"
                      : "",
                )}{" "}
              </span>
            </footer>
          </article>
        ))}
      </div>
      <div className="library-note">
        <Layers size={21} />
        <div>
          <strong> {t("Room to grow")} </strong>
          <p>
            {" "}
            {t(
              "More local models and creative tools can join the same projects and asset library. Standalone audio generation is planned.",
            )}{" "}
          </p>
        </div>
      </div>
      {dialog ? (
        <Modal
          title={
            dialog.action === "install"
              ? t(`Install ${dialog.model.name}`)
              : t(`Delete ${dialog.model.name}`)
          }
          onClose={() => !busy && setDialog(null)}
        >
          <div className="dialog-body form-stack">
            {dialog.action === "install" ? (
              <>
                <p>
                  {" "}
                  {t("This installs approximately")}{" "}
                  <strong>
                    {dialog.model.download_gb} {t("GB")}{" "}
                  </strong>{" "}
                  {t(
                    "of weights plus an isolated GPU runtime, inside Local Atelier's models folder.",
                  )}{" "}
                </p>
                <p>
                  {" "}
                  {t(
                    "Requires Windows, uv and an NVIDIA GPU. You can keep browsing while installation runs.",
                  )}{" "}
                </p>
                <ExternalLink href={dialog.model.license_url}>
                  {" "}
                  {t("Read the model's")} {t(dialog.model.license)}{" "}
                </ExternalLink>
              </>
            ) : (
              <p>
                {" "}
                {t(
                  "This permanently deletes the runtime and downloaded weights owned by Local Atelier (",
                )}{" "}
                {t(bytes(dialog.model.size_bytes))}{" "}
                {t(
                  "). Project images, meshes and clips remain in your library. You can install the model again later.",
                )}{" "}
              </p>
            )}
            {error ? (
              <p className="error" role="alert">
                {" "}
                {t(error)}{" "}
              </p>
            ) : null}
            <div className="dialog-actions">
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setDialog(null)}
              >
                {" "}
                {t("Cancel")}{" "}
              </button>
              <button
                className={
                  dialog.action === "remove" ? "danger-button" : "primary"
                }
                disabled={busy}
                onClick={() => void action(dialog.model, dialog.action)}
              >
                {" "}
                {t(
                  busy
                    ? "Working…"
                    : dialog.action === "install"
                      ? "Install model"
                      : "Delete model",
                )}{" "}
              </button>
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
