import { useEffect, useState, type FormEvent } from "react";
import { KeyRound, LockKeyhole, ShieldCheck } from "lucide-react";
import { post } from "./api";
import { t } from "./i18n";
import { Modal } from "./ui";

export type PersonalAction = "setup" | "unlock" | "password";

export function PersonalDialog({
  mode,
  onClose,
  onComplete,
}: {
  mode: PersonalAction;
  onClose: () => void;
  onComplete: (entered: boolean) => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [current, setCurrent] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const choosing = mode !== "unlock";
  const title =
    mode === "setup"
      ? "Set personal password"
      : mode === "password"
        ? "Change personal password"
        : "Enter personal space";
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (choosing && password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await post(`/personal/${mode}`, {
        password,
        ...(mode === "password" ? { current_password: current } : {}),
      });
      setPassword("");
      setCurrent("");
      setConfirmation("");
      await onComplete(mode !== "password");
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t(title)}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="dialog-body form-stack personal-form"
        onSubmit={(e) => void submit(e)}
      >
        <p>
          {t(
            mode === "setup"
              ? "A separate home for your private projects, images, videos and meshes. Everything you save here stays encrypted on this device."
              : mode === "password"
                ? "Your saved work stays in place. The new password will unlock it next time."
                : "Unlock your saved projects and creations for this session.",
          )}
        </p>
        {mode === "password" && (
          <label>
            {t("Current password")}
            <input
              autoFocus
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              maxLength={1024}
              disabled={busy}
            />
          </label>
        )}
        <label>
          {t(choosing ? "New password" : "Personal password")}
          <input
            autoFocus={mode !== "password"}
            type="password"
            autoComplete={choosing ? "new-password" : "current-password"}
            required
            minLength={choosing ? 12 : undefined}
            maxLength={1024}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
            aria-describedby="personal-password-help"
          />
        </label>
        {choosing && (
          <label>
            {t("Confirm password")}
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              maxLength={1024}
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              disabled={busy}
            />
          </label>
        )}
        <p className="muted-text" id="personal-password-help">
          {t(
            choosing
              ? "Use at least 12 characters. A long, unique passphrase is best. There is no password reset: losing it means losing access to this space."
              : "Locks when you leave or reload this page, after 15 minutes without activity, or when the studio restarts.",
          )}
        </p>
        {error && (
          <p className="error-banner" role="alert">
            {t(error)}
          </p>
        )}
        <div className="dialog-actions">
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            {t("Cancel")}
          </button>
          <button className="primary" disabled={busy}>
            <KeyRound size={16} />
            {t(
              busy
                ? "Unlocking encrypted storage…"
                : mode === "setup"
                  ? "Set password and enter"
                  : mode === "password"
                    ? "Save password"
                    : "Unlock personal space",
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function PersonalBar({ onLock }: { onLock: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let lastTouch = 0;
    const touch = () => {
      if (Date.now() - lastTouch < 30000) return;
      lastTouch = Date.now();
      void post("/personal/touch").catch(() =>
        window.dispatchEvent(new Event("atelier-space-locked")),
      );
    };
    const close = () => navigator.sendBeacon("/api/personal/lock");
    const restore = (event: PageTransitionEvent) => {
      if (event.persisted) location.replace("/settings?locked=1");
    };
    window.addEventListener("pointerdown", touch);
    window.addEventListener("keydown", touch);
    window.addEventListener("scroll", touch, true);
    window.addEventListener("pagehide", close);
    window.addEventListener("pageshow", restore);
    return () => {
      window.removeEventListener("pointerdown", touch);
      window.removeEventListener("keydown", touch);
      window.removeEventListener("scroll", touch, true);
      window.removeEventListener("pagehide", close);
      window.removeEventListener("pageshow", restore);
    };
  }, []);
  return (
    <div
      className="temporary-bar personal-bar"
      role="region"
      aria-label={t("Personal space")}
    >
      <strong>
        <ShieldCheck size={17} />
        {t("Personal space")}
      </strong>
      <span>{t("Saved privately · encrypted on disk")}</span>
      <button
        className="quiet"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onLock();
          } catch (e) {
            setError((e as Error).message);
            setBusy(false);
          }
        }}
      >
        <LockKeyhole size={16} />
        {t(busy ? "Locking…" : "Lock and leave")}
      </button>
      {error && (
        <p className="error" role="alert">
          {t(error)}
        </p>
      )}
    </div>
  );
}
