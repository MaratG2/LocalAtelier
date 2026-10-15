import { useState } from "react";
import { LoaderCircle, Trash2 } from "lucide-react";
import { api, patch } from "./api";
import { t } from "./i18n";
import { Modal } from "./ui";
import type { Asset } from "./types";

export function AssetDeleteDialog({ asset, onClose, onDeleted }: {
  asset: Asset;
  onClose: () => void;
  onDeleted: (asset: Asset) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const permanent = !!asset.deleted;
  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (permanent) await api(`/assets/${asset.id}`, { method: "DELETE" });
      else await patch(`/assets/${asset.id}`, { deleted: true });
      onDeleted(asset);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <Modal title={permanent ? "Delete permanently?" : "Move to Trash?"}
      onClose={() => { if (!busy) onClose(); }}>
      <div className="dialog-body delete-generation-dialog" aria-busy={busy}>
        <div className="delete-generation-preview">
          <img src={asset.thumbnail_url} alt="" />
          <div><strong>{asset.name}</strong><span>{t(asset.personal ? "Personal space" : "Generation")}</span></div>
        </div>
        <p>{t(permanent
          ? "This permanently deletes the generation and its saved files, including previews. This cannot be undone."
          : "This generation will be hidden from your library. You can restore it or delete it permanently from Trash.")}</p>
        {error && <p className="error-banner" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button className="secondary" data-dialog-autofocus disabled={busy} onClick={onClose}>{t("Cancel")}</button>
          <button className="danger-button" disabled={busy} onClick={() => void confirm()}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <Trash2 size={16} />}
            {t(busy ? "Deleting…" : permanent ? "Delete permanently" : "Move to trash")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
