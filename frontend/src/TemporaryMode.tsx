import { t } from "./i18n";
import { useEffect, useState } from "react";
import { EyeOff, Download, X } from "lucide-react";
import { api, post } from "./api";
import { Modal } from "./ui";
import type { Asset, Snapshot } from "./types";

export function TemporaryMode({
  snapshot,
  changed,
}: {
  snapshot: Snapshot;
  changed: () => Promise<void>;
}) {
  const temporary = !!snapshot.status?.temporary;
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState<Asset[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const key = snapshot.jobs.map((j) => j.id + ":" + j.completed).join("|");
  useEffect(() => {
    if (!temporary) {
      setResults([]);
      setDismissed(new Set());
      return;
    }
    let active = true;
    void api<Asset[]>("/assets?kind=all")
      .then((values) => {
        if (active) setResults(values);
      })
      .catch((e) => setError(e.message));
    return () => {
      active = false;
    };
  }, [key, temporary]);
  useEffect(() => {
    if (!temporary) return;
    const close = () =>
      navigator.sendBeacon(
        "/api/temporary/close",
        new Blob(["{}"], { type: "application/json" }),
      );
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("pagehide", close);
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("pagehide", close);
      window.removeEventListener("beforeunload", warn);
    };
  }, [temporary]);
  const toggle = async () => {
    setBusy(true);
    setError("");
    try {
      const response = temporary
        ? await api<{ cleanup_error?: string }>("/temporary", {
            method: "DELETE",
          })
        : await post<{ cleanup_error?: string }>("/temporary");
      setConfirm(false);
      await changed();
      if (response.cleanup_error) setError(response.cleanup_error);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const pending = results.filter((a) => !dismissed.has(a.id));
  return (
    <>
      <div className={`temporary-bar ${temporary ? "enabled" : ""}`}>
        <button
          type="button"
          className="quiet"
          role="switch"
          aria-checked={temporary}
          disabled={busy}
          onClick={() => setConfirm(true)}
        >
          <EyeOff size={17} />{" "}
          {t(temporary ? "Incognito on" : "Incognito off")}{" "}
        </button>
        <span>
          {" "}
          {t(
            temporary
              ? "Temporary workspace · download results before leaving"
              : "Generations are saved to your project",
          )}{" "}
        </span>
        {error && (
          <p className="error" role="alert">
            {" "}
            {t(error)}{" "}
          </p>
        )}
      </div>
      {confirm && (
        <Modal
          title={t(
            temporary ? "End temporary session?" : "Start incognito mode?",
          )}
          onClose={() => setConfirm(false)}
        >
          <div className="dialog-body form-stack">
            <p>
              {" "}
              {t(
                temporary
                  ? "Unsaved results and uploads will be discarded. Active temporary jobs will be cancelled."
                  : "Images, 3D and video will use a temporary workspace in this browser. Prompts and results are excluded from project history. Existing drafts remain unchanged.",
              )}{" "}
            </p>
            <p>
              {" "}
              {t(
                "GPU workers use temporary files on disk. Cleanup runs after active workers stop, when you end the session, close or reload the tab, or after 15 minutes disconnected. After a crash, cleanup retries on the next studio start. This is not secure disk erasure.",
              )}{" "}
            </p>
            <div className="dialog-actions">
              <button className="secondary" onClick={() => setConfirm(false)}>
                {" "}
                {t("Keep working")}{" "}
              </button>
              <button
                className="primary"
                disabled={busy}
                onClick={() => void toggle()}
              >
                {" "}
                {t(
                  temporary
                    ? "Discard and end session"
                    : "Start temporary session",
                )}{" "}
              </button>
            </div>
          </div>
        </Modal>
      )}
      {temporary && pending.length > 0 && (
        <aside
          className="temporary-results"
          aria-label={t("Save temporary results")}
          role="status"
        >
          <strong> {t("Save now or lose it when this session ends")} </strong>
          {pending.map((a) => (
            <div key={a.id}>
              <img src={a.thumbnail_url} alt="" />
              <span>{a.name}</span>
              <a className="secondary" href={a.url + "?download=true"} download>
                <Download size={16} /> {t("Download")}{" "}
              </a>
              <button
                className="icon-btn"
                aria-label={t("Dismiss save reminder")}
                onClick={() => setDismissed((old) => new Set([...old, a.id]))}
              >
                <X size={16} />
              </button>
            </div>
          ))}
          <small>
            {" "}
            {t(
              "Downloads are your choice and remain on disk. Dismissing this reminder does not save the file.",
            )}{" "}
          </small>
        </aside>
      )}
    </>
  );
}
