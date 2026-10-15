import { t, projectName, quantity, number } from "./i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AudioLines,
  ChevronDown,
  Download,
  Film,
  Folder,
  ImagePlus,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Star,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, patch, post } from "./api";
import { Modal } from "./ui";
import { AssetDeleteDialog } from "./AssetDeleteDialog";
import VideoPlayer from "./VideoPlayer";
import type { Asset, Job, Snapshot, VideoRequest } from "./types";
import "./video.css";

const ACTIVE = new Set(["queued", "running"]);
const defaults = {
  prompt: "",
  quality: "light" as VideoRequest["quality"],
  width: 896,
  height: 512,
  seconds: 5,
  seed: 42,
  preview: true,
};
const qualityCopy = {
  light: "8 steps + a 3-step finish. Preview first to explore ideas.",
  medium: "12 steps at full resolution. A single pass.",
  high: "16 steps at full resolution. More time for detail.",
  max: "20 steps at full resolution. The longest render.",
};
const duration = (asset: Asset) =>
  `${Number(asset.metadata.duration || 0).toFixed(1)}s`;

export default function VideoStudio({
  snapshot,
  projectId,
  onProject,
  navigate,
  notify,
  refresh,
}: {
  snapshot: Snapshot;
  projectId: string;
  onProject: (id: string) => void;
  navigate: (path: string, project?: string) => void;
  notify: (message: string) => void;
  refresh: () => Promise<void>;
}) {
  const [form, setForm] = useState(() => {
    try {
      if (snapshot.status?.temporary || snapshot.status?.personal) return defaults;
      return {
        ...defaults,
        ...JSON.parse(
          localStorage.getItem(`atelier.video.${projectId}`) || "{}",
        ),
      } as typeof defaults;
    } catch {
      return defaults;
    }
  });
  const [mode, setMode] = useState<"text" | "frames" | "references">("text");
  const [first, setFirst] = useState<Asset | null>(null);
  const [last, setLast] = useState<Asset | null>(null);
  const [refs, setRefs] = useState<Asset[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pendingJob, setPendingJob] = useState<string | null>(null);
  const [picker, setPicker] = useState<"first" | "last" | "reference" | null>(
    null,
  );
  const [images, setImages] = useState<Asset[]>([]);
  const [dialog, setDialog] = useState<"export" | "details" | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  const uploadTarget = useRef<"first" | "last" | "reference">("reference");
  const currentFilter = useRef("");
  currentFilter.current = JSON.stringify([projectId, filter, query]);
  const selected = assets.find((a) => a.id === selectedId) || assets[0] || null;
  const model = snapshot.models.find((m) => m.id === "vdn-h3");
  const jobs = snapshot.jobs.filter(
    (j) => j.model_id === "vdn-h3" && j.project_id === projectId,
  );
  const active = jobs.filter((j) => ACTIVE.has(j.status));
  const failed = jobs.find(
    (j) => j.status === "error" && Date.now() / 1000 - j.created < 3600,
  );
  const loadAssets = useCallback(async () => {
    const signature = JSON.stringify([projectId, filter, query]);
    try {
      const result = await api<Asset[]>(
        `/assets?${new URLSearchParams({ kind: "video", project: projectId, q: query, favorite: String(filter === "favorites"), trash: String(filter === "trash") })}`,
      );
      if (signature === currentFilter.current) setAssets(result);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId, filter, query]);
  useEffect(() => {
    const timer = setTimeout(() => void loadAssets(), 150);
    return () => clearTimeout(timer);
  }, [loadAssets, snapshot.jobs]);
  useEffect(() => {
    if (snapshot.status?.temporary || snapshot.status?.personal) return;
    localStorage.setItem(`atelier.video.${projectId}`, JSON.stringify(form));
  }, [form, projectId]);
  useEffect(() => {
    const image = new URLSearchParams(location.search).get("image");
    if (image)
      void api<Asset>(`/assets/${encodeURIComponent(image)}`)
        .then((a) => {
          if (a.kind === "generated" || a.kind === "reference") {
            setFirst(a);
            setMode("frames");
          }
        })
        .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    const job = jobs.find((j) => j.id === pendingJob);
    if (job?.status === "complete") {
      setSelectedId(job.result_ids[0]);
      setFilter("all");
      setQuery("");
      setPendingJob(null);
      notify("Your clip is ready");
    } else if (job && !ACTIVE.has(job.status)) setPendingJob(null);
  }, [jobs, pendingJob, notify]);
  const choose = (asset: Asset, target: "first" | "last" | "reference") => {
    if (target === "first") setFirst(asset);
    else if (target === "last") setLast(asset);
    else
      setRefs((values) =>
        values.some((v) => v.id === asset.id)
          ? values
          : [...values, asset].slice(0, 12),
      );
    setPicker(null);
  };
  const upload = async (file?: File) => {
    if (!file) return;
    const target = uploadTarget.current;
    setBusy(true);
    setError("");
    try {
      const image = file.type.startsWith("image/");
      const body = new FormData();
      body.append(image ? "image" : "media", file);
      body.append("project_id", projectId);
      choose(
        await api<Asset>(image ? "/uploads" : "/videos/uploads", {
          method: "POST",
          body,
        }),
        target,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (uploadInput.current) uploadInput.current.value = "";
    }
  };
  const openUpload = (target: "first" | "last" | "reference") => {
    uploadTarget.current = target;
    if (uploadInput.current) {
      uploadInput.current.accept =
        target === "reference"
          ? "image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime,audio/*"
          : "image/png,image/jpeg,image/webp";
      uploadInput.current.click();
    }
  };
  const openPicker = async (target: "first" | "last" | "reference") => {
    try {
      const candidates = await api<Asset[]>(
        `/assets?project=${projectId}&kind=${target === "reference" ? "all" : "image"}`,
      );
      setImages(
        candidates.filter(
          (asset) =>
            asset.kind === "generated" ||
            (target === "reference" && asset.kind === "video"),
        ),
      );
      setPicker(target);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const submit = async (finish = false) => {
    setBusy(true);
    setError("");
    try {
      const payload =
        finish && selected
          ? {
              project_id: projectId,
              model_id: "vdn-h3",
              mode: "finish",
              source_video_id: selected.id,
            }
          : {
              ...form,
              project_id: projectId,
              model_id: "vdn-h3",
              mode,
              first_id: mode === "frames" ? first?.id : null,
              last_id: mode === "frames" ? last?.id : null,
              reference_ids: mode === "references" ? refs.map((r) => r.id) : [],
            };
      const job = await post<Job>("/videos/jobs", payload);
      setPendingJob(job.id);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const updateAsset = async (changes: Record<string, unknown>) => {
    if (!selected) return;
    try {
      await patch(`/assets/${selected.id}`, changes);
      await loadAssets();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const reuse = async () => {
    if (!selected) return;
    const settings = selected.metadata.settings as unknown as
      | VideoRequest
      | undefined;
    if (!settings) return;
    setForm({
      prompt: settings.prompt,
      quality: settings.quality,
      width: settings.width,
      height: settings.height,
      seconds: settings.seconds,
      seed: settings.seed,
      preview: settings.preview,
    });
    setMode(
      settings.first_id || settings.last_id
        ? "frames"
        : settings.reference_ids.length
          ? "references"
          : "text",
    );
    try {
      const [firstAsset, lastAsset, referenceAssets] = await Promise.all([
        settings.first_id ? api<Asset>(`/assets/${settings.first_id}`) : null,
        settings.last_id ? api<Asset>(`/assets/${settings.last_id}`) : null,
        Promise.all(
          settings.reference_ids.map((id) => api<Asset>(`/assets/${id}`)),
        ),
      ]);
      setFirst(firstAsset);
      setLast(lastAsset);
      setRefs(referenceAssets);
      notify("Settings loaded");
    } catch {
      setError(
        "Settings loaded, but a reference is no longer available. Choose a replacement before generating.",
      );
    }
  };
  const alignedFrames =
    Math.ceil(form.seconds * 24) +
    ((5 - (Math.ceil(form.seconds * 24) % 17) + 17) % 17);
  const frameSlot = (target: "first" | "last", asset: Asset | null) => (
    <div className="video-frame-slot">
      <span> {t(target === "first" ? "First frame" : "Last frame")} </span>
      {asset ? (
        <div className="video-frame-image">
          <img src={asset.thumbnail_url} alt={asset.name} />
          <button
            className="icon-btn"
            aria-label={t(`Remove ${target} frame`)}
            onClick={() =>
              target === "first" ? setFirst(null) : setLast(null)
            }
          >
            <X size={14} />
          </button>
        </div>
      ) : (
        <button className="video-frame-add" onClick={() => openUpload(target)}>
          <ImagePlus size={21} />
          <span> {t("Add image")} </span>
        </button>
      )}
      <button className="text-link" onClick={() => void openPicker(target)}>
        {" "}
        {t("From project")}{" "}
      </button>
    </div>
  );
  return (
    <div className="video-page">
      <header className="page-head">
        <div>
          <h1> {t("Video studio")} </h1>
          <p> {t("Bring your ideas into motion.")} </p>
        </div>
        <label className="video-project">
          <Folder size={17} />
          <select
            aria-label={t("Video project")}
            value={projectId}
            onChange={(e) => onProject(e.target.value)}
          >
            {snapshot.projects.map((p) => (
              <option value={p.id} key={p.id}>
                {" "}
                {projectName(p)}{" "}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div className="video-workspace">
        <section
          className="video-config"
          aria-label={t("Video generation settings")}
        >
          <div className="segmented video-modes">
            {(["text", "frames", "references"] as const).map((value) => (
              <button
                key={value}
                className={mode === value ? "active" : ""}
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {" "}
                {t(value[0].toUpperCase() + value.slice(1))}{" "}
              </button>
            ))}
          </div>
          <label className="video-field">
            {" "}
            {t("Prompt")}{" "}
            <textarea
              value={form.prompt}
              maxLength={12000}
              onChange={(e) => setForm({ ...form, prompt: e.target.value })}
              placeholder={t("Describe the scene, movement and sound…")}
              rows={5}
            />
          </label>
          <p className="video-hint">
            {" "}
            {t(
              "Describe movement, camera direction, dialogue and atmosphere.",
            )}{" "}
          </p>
          {mode === "frames" && (
            <>
              <div className="video-frames">
                {frameSlot("first", first)}
                {frameSlot("last", last)}
              </div>
              <p className="video-hint">
                {" "}
                {t(
                  "Use either frame, or both to guide the beginning and end.",
                )}{" "}
              </p>
            </>
          )}
          {mode === t("references") && (
            <div className="video-references">
              <div className="video-field-heading">
                <strong> {t("References")} </strong>
                <span>{refs.length}/12</span>
              </div>
              {refs.map((ref, index) => (
                <div className="video-reference-row" key={ref.id}>
                  <img src={ref.thumbnail_url} alt="" />
                  <span>
                    <strong>
                      {" "}
                      {t("Reference")} {index + 1}
                    </strong>
                    <small>{ref.name}</small>
                  </span>
                  <button
                    className="icon-btn"
                    aria-label={t(`Remove reference ${index + 1}`)}
                    onClick={() => setRefs(refs.filter((r) => r.id !== ref.id))}
                  >
                    <X size={15} />
                  </button>
                </div>
              ))}
              <div className="video-reference-actions">
                <button
                  className="secondary"
                  disabled={busy || refs.length >= 12}
                  onClick={() => openUpload("reference")}
                >
                  <Upload size={15} /> {t("Upload")}{" "}
                </button>
                <button
                  className="secondary"
                  disabled={refs.length >= 12}
                  onClick={() => void openPicker("reference")}
                >
                  <Plus size={15} /> {t("Project")}{" "}
                </button>
              </div>
              <p className="video-hint">
                {" "}
                {t(
                  "Up to 9 images, 3 videos and 3 audio clips. Media: 2–15 seconds, 64 MB each. Combined video and audio: 15 seconds each.",
                )}{" "}
              </p>
            </div>
          )}
          <div className="video-field">
            <span> {t("Model")} </span>
            <button className="video-model" onClick={() => navigate("/models")}>
              <span className="video-model-mark">H3</span>
              <span>
                <strong>VDN-H3</strong>
                <small> {t("Powered by MiniMax H3")} </small>
              </span>
              <ChevronDown size={16} />
            </button>
          </div>
          <div className="video-field">
            <span> {t("Quality")} </span>
            <div className="segmented video-quality">
              {(["light", "medium", "high", "max"] as const).map((q) => (
                <button
                  key={q}
                  className={form.quality === q ? "active" : ""}
                  aria-pressed={form.quality === q}
                  onClick={() =>
                    setForm({
                      ...form,
                      quality: q,
                      preview: q === "light" ? form.preview : false,
                    })
                  }
                >
                  {" "}
                  {t(q[0].toUpperCase() + q.slice(1))}{" "}
                </button>
              ))}
            </div>
          </div>
          <p className="video-hint"> {t(qualityCopy[form.quality])} </p>
          <div className="video-fields-row">
            <label className="video-field">
              {" "}
              {t("Canvas")}{" "}
              <select
                value={`${form.width}x${form.height}`}
                onChange={(e) => {
                  const [width, height] = e.target.value.split("x").map(Number);
                  setForm({ ...form, width, height });
                }}
              >
                <option value="896x512"> {t("896 × 512 · Wide")} </option>
                <option value="512x896"> {t("512 × 896 · Tall")} </option>
                <option value="512x512"> {t("512 × 512 · Square")} </option>
                <option value="1344x768"> {t("1344 × 768 · Wide")} </option>
                <option value="768x1344"> {t("768 × 1344 · Tall")} </option>
                <option value="768x768"> {t("768 × 768 · Square")} </option>
              </select>
            </label>
            <label className="video-field">
              {" "}
              {t("Duration")}{" "}
              <select
                value={form.seconds}
                onChange={(e) =>
                  setForm({ ...form, seconds: Number(e.target.value) })
                }
              >
                {[2, 3, 5, 8, 10].map((s) => (
                  <option key={s} value={s}>
                    {quantity(s, "seconds")}{" "}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="video-hint">
            {" "}
            {number(alignedFrames / 24, 2)}{" "}
            {t(
              "s at 24 fps after frame alignment. Stereo sound is generated with every clip.",
            )}{" "}
          </p>
          <label
            className={`video-toggle ${form.quality !== "light" ? "muted-text" : ""}`}
          >
            <span>
              <strong> {t("Preview first")} </strong>
              <small> {t("Explore at half resolution, finish later.")} </small>
            </span>
            <input
              type="checkbox"
              checked={form.preview}
              disabled={form.quality !== "light"}
              onChange={(e) => setForm({ ...form, preview: e.target.checked })}
            />
          </label>
          <button
            className="video-more"
            aria-expanded={advanced}
            onClick={() => setAdvanced(!advanced)}
          >
            <SlidersHorizontal size={16} /> {t("More settings")}{" "}
            <ChevronDown size={16} />
          </button>
          {advanced && (
            <label className="video-field">
              {" "}
              {t("Seed")}{" "}
              <div className="video-seed">
                <input
                  type="number"
                  min={0}
                  max={4294967295}
                  value={form.seed}
                  onChange={(e) =>
                    setForm({ ...form, seed: Number(e.target.value) })
                  }
                />
                <button
                  className="icon-btn"
                  aria-label={t("Randomize seed")}
                  onClick={() =>
                    setForm({
                      ...form,
                      seed: crypto.getRandomValues(new Uint32Array(1))[0],
                    })
                  }
                >
                  <RefreshCw size={16} />
                </button>
              </div>
            </label>
          )}
          {error && (
            <div className="error-banner" role="alert">
              {" "}
              {t(error)}{" "}
              <button
                aria-label={t("Dismiss error")}
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {model?.status !== "installed" ? (
            <div className="video-install">
              <p>
                {" "}
                {t(
                  model?.busy
                    ? model.operation?.phase
                    : "Install VDN-H3 to start creating video.",
                )}{" "}
              </p>
              <button className="secondary" onClick={() => navigate("/models")}>
                {" "}
                {t("Open model library")}{" "}
              </button>
            </div>
          ) : null}
          <button
            className="primary video-generate"
            disabled={
              busy ||
              !form.prompt.trim() ||
              model?.status !== "installed" ||
              !!model?.busy ||
              (mode === "frames" && !first && !last) ||
              (mode === "references" && !refs.length)
            }
            onClick={() => void submit()}
          >
            {busy ? (
              <LoaderCircle size={18} className="spin" />
            ) : (
              <Film size={18} />
            )}{" "}
            {t(form.preview ? "Generate preview" : "Generate video")}{" "}
          </button>
          <p className="video-local-note">
            {" "}
            {t("Runs on your GPU · No credits")}{" "}
          </p>
        </section>
        <section className="video-stage" aria-label={t("Video preview")}>
          {active.map((job) => (
            <div className="video-job" key={job.id}>
              <p className="video-job-prompt" title={job.request.prompt}>
                {" "}
                {t(job.request.mode === "finish" ? "Finishing · " : "")}{" "}
                {job.request.prompt}
              </p>
              <div>
                <LoaderCircle size={16} className="spin" />
                <strong> {t(job.phase)} </strong>
                <button
                  className="text-link"
                  onClick={() =>
                    void post(`/jobs/${job.id}/cancel`)
                      .then(refresh)
                      .catch((e) => setError(e.message))
                  }
                >
                  {" "}
                  {t("Cancel")}{" "}
                </button>
              </div>
              {job.progress > 0 ? (
                <progress
                  max={100}
                  value={job.progress}
                  aria-label={t("Current render stage progress")}
                />
              ) : (
                <p>
                  {" "}
                  {t(
                    job.status === "queued"
                      ? "Waiting for the current GPU job to finish."
                      : "Preparing this clip. The first render includes kernel compilation.",
                  )}{" "}
                </p>
              )}
            </div>
          ))}
          {failed && (
            <details className="video-job-error">
              <summary> {t("Latest render needs attention")} </summary>
              <p> {t(failed.error)} </p>
              <button
                className="text-link"
                onClick={() => navigate("/settings")}
              >
                {" "}
                {t("View runtime logs")}{" "}
              </button>
            </details>
          )}
          {selected ? (
            <>
              <VideoPlayer key={selected.id} asset={selected} />
              <div className="video-result">
                <div className="video-result-heading">
                  <div>
                    <h2>{selected.name}</h2>
                    <p>
                      {" "}
                      {t(
                        selected.metadata.preview ? "Preview" : "Finished",
                      )}{" "}
                      {t("· VDN-H3 ·")} {t(duration(selected))} ·{" "}
                      {selected.width} × {selected.height} {t("· Stereo")}{" "}
                    </p>
                  </div>
                  <button
                    className={`icon-btn ${selected.favorite ? "is-favorite" : ""}`}
                    aria-label={t(
                      selected.favorite
                        ? "Remove clip from favorites"
                        : "Favorite clip",
                    )}
                    onClick={() =>
                      void updateAsset({ favorite: !selected.favorite })
                    }
                  >
                    <Star
                      size={19}
                      fill={selected.favorite ? "currentColor" : "none"}
                    />
                  </button>
                </div>
                <div className="video-result-actions">
                  <button className="secondary" disabled={!!selected.deleted} onClick={() => void reuse()}>
                    <RefreshCw size={15} /> {t("Use settings")}{" "}
                  </button>
                  {selected.metadata.preview && !selected.deleted ? (
                    <button
                      className="primary"
                      disabled={
                        busy || model?.status !== "installed" || !!model?.busy
                      }
                      onClick={() => void submit(true)}
                    >
                      {" "}
                      {t("Finish preview")}{" "}
                    </button>
                  ) : null}
                  <button
                    className="secondary"
                    onClick={() => setDialog("export")}
                  >
                    <Download size={16} /> {t("Download")}{" "}
                  </button>
                  <button
                    className="icon-btn"
                    aria-label={t("Clip details")}
                    onClick={() => setDialog("details")}
                  >
                    <SlidersHorizontal size={17} />
                  </button>
                  <button
                    className="icon-btn"
                    aria-label={t(
                      selected.deleted ? "Restore clip" : "Move clip to trash",
                    )}
                    onClick={() =>
                      selected.deleted ? void updateAsset({ deleted: false }) : setDeleteTarget(selected)
                    }
                  >
                    {selected.deleted ? (
                      <RefreshCw size={17} />
                    ) : (
                      <Trash2 size={17} />
                    )}
                  </button>
                  {!!selected.deleted && <button className="quiet danger" onClick={() => setDeleteTarget(selected)}>
                    <Trash2 size={17} />{t("Delete permanently")}
                  </button>}
                </div>
                {selected.metadata.preview ? (
                  <p className="video-hint">
                    {" "}
                    {t("Finish at")}{" "}
                    {t(
                      String(
                        (selected.metadata.settings as unknown as VideoRequest)
                          ?.width,
                      ),
                    )}{" "}
                    ×{" "}
                    {t(
                      String(
                        (selected.metadata.settings as unknown as VideoRequest)
                          ?.height,
                      ),
                    )}{" "}
                    {t(
                      "using the saved first pass. Your preview is kept.",
                    )}{" "}
                  </p>
                ) : null}
              </div>
            </>
          ) : (
            <div className="video-empty">
              <div className="video-empty-symbol">
                <Film size={35} strokeWidth={1.3} />
              </div>
              <h2> {t("A little movement changes everything.")} </h2>
              <p>
                {" "}
                {t(
                  "Describe a scene and its sound, or start with an image. Your clips will appear here.",
                )}{" "}
              </p>
              <div>
                <span> {t("01 · Describe")} </span>
                <span> {t("02 · Preview")} </span>
                <span> {t("03 · Finish")} </span>
              </div>
            </div>
          )}
        </section>
        <aside className="video-library" aria-label={t("Project clips")}>
          <div className="video-library-heading">
            <h2> {t("Project clips")} </h2>
            <span>{assets.length}</span>
          </div>
          <label className="video-search">
            <Search size={16} />
            <input
              aria-label={t("Search clips")}
              placeholder={t("Search clips")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="segmented video-filters">
            <button
              className={filter === "all" ? "active" : ""}
              onClick={() => setFilter("all")}
            >
              {" "}
              {t("All")}{" "}
            </button>
            <button
              className={filter === "favorites" ? "active" : ""}
              aria-label={t("Favorite clips")}
              onClick={() => setFilter("favorites")}
            >
              <Star size={15} />
            </button>
            <button
              className={filter === "trash" ? "active" : ""}
              aria-label={t("Trashed clips")}
              onClick={() => setFilter("trash")}
            >
              <Trash2 size={15} />
            </button>
          </div>
          <div className="video-clip-list">
            {assets.map((asset) => (
              <button
                className={`video-clip-card ${selected?.id === asset.id ? "selected" : ""}`}
                key={asset.id}
                onClick={() => setSelectedId(asset.id)}
              >
                <div>
                  <img src={asset.thumbnail_url} alt="" loading="lazy" />
                  <span> {t(duration(asset))} </span>
                </div>
                <strong>{asset.name}</strong>
                <small>
                  {" "}
                  {t(asset.metadata.preview ? "Preview" : "Finished")}{" "}
                  {t(asset.favorite ? " · Favorite" : "")}{" "}
                </small>
              </button>
            ))}
          </div>
          {!assets.length && (
            <p className="video-library-empty">
              {" "}
              {t(
                filter === "trash"
                  ? "Your trash is empty."
                  : query
                    ? "No matching clips."
                    : filter === "favorites"
                      ? "Favorite a clip to find it here."
                      : "Your project’s clips, all in one place.",
              )}{" "}
            </p>
          )}
        </aside>
      </div>
      <input
        ref={uploadInput}
        type="file"
        hidden
        onChange={(e) => void upload(e.target.files?.[0])}
      />
      {picker && (
        <Modal
          title={t(
            picker === "reference"
              ? "Choose a project reference"
              : "Choose a project image",
          )}
          onClose={() => setPicker(null)}
        >
          <div className="video-image-picker">
            {images.map((image) => (
              <button key={image.id} onClick={() => choose(image, picker)}>
                <img src={image.thumbnail_url} alt={image.name} />
                <span>{image.name}</span>
              </button>
            ))}
          </div>
          {!images.length && (
            <p>
              {" "}
              {t(
                "No matching assets in this project yet. Upload a reference or create one in the studio.",
              )}{" "}
            </p>
          )}
          <button className="secondary" onClick={() => openUpload(picker)}>
            <Upload size={16} />{" "}
            {t(
              picker === "reference" ? "Upload reference" : "Upload image",
            )}{" "}
          </button>
        </Modal>
      )}
      {dialog === "export" && selected && (
        <Modal title={t("Download clip")} onClose={() => setDialog(null)}>
          <div className="video-downloads">
            <a className="secondary" href={`${selected.url}?download=true`}>
              <Film size={19} />
              <span>
                <strong> {t("Video with sound")} </strong>
                <small>
                  {" "}
                  {t("MP4 ·")} {selected.width} × {selected.height}
                </small>
              </span>
              <Download size={17} />
            </a>
            <a className="secondary" href={`/api/videos/${selected.id}/audio`}>
              <AudioLines size={19} />
              <span>
                <strong> {t("Audio only")} </strong>
                <small> {t("WAV · Stereo · 32 kHz")} </small>
              </span>
              <Download size={17} />
            </a>
            <a
              className="secondary"
              href={`/api/assets/${selected.id}/thumbnail?download=true`}
            >
              <ImagePlus size={19} />
              <span> {t("Cover image · PNG")} </span>
              <Download size={17} />
            </a>
            <a
              className="secondary"
              href={`/api/assets/${selected.id}/metadata`}
              download={`atelier-${selected.id}.json`}
            >
              <SlidersHorizontal size={19} />
              <span> {t("Generation settings · JSON")} </span>
              <Download size={17} />
            </a>
          </div>
        </Modal>
      )}
      {dialog === "details" && selected && (
        <Modal title={t("Clip details")} onClose={() => setDialog(null)}>
          <label className="video-field">
            {" "}
            {t("Name")}{" "}
            <input
              defaultValue={selected.name}
              key={selected.id}
              maxLength={120}
              onBlur={(e) => {
                if (e.target.value.trim() && e.target.value !== selected.name)
                  void updateAsset({ name: e.target.value.trim() });
              }}
            />
          </label>
          <label className="video-field">
            {" "}
            {t("Project")}{" "}
            <select
              value={selected.project_id}
              onChange={(e) => {
                void updateAsset({ project_id: e.target.value });
                setDialog(null);
              }}
            >
              {snapshot.projects.map((p) => (
                <option value={p.id} key={p.id}>
                  {" "}
                  {projectName(p)}{" "}
                </option>
              ))}
            </select>
          </label>
          <p className="video-detail-prompt">{selected.prompt}</p>
          <dl className="video-details-list">
            <dt> {t("Model")} </dt>
            <dd>VDN-H3 · MiniMax H3</dd>
            <dt> {t("Seed")} </dt>
            <dd>{selected.seed}</dd>
            <dt> {t("Render time")} </dt>
            <dd>
              {" "}
              {t(Number(selected.metadata.elapsed_seconds).toFixed(1))}{" "}
              {t("seconds")}{" "}
            </dd>
            <dt> {t("Frames / FPS")} </dt>
            <dd>
              {" "}
              {t(String(selected.metadata.frames))} /{" "}
              {t(String(selected.metadata.fps))}{" "}
            </dd>
            <dt> {t("Audio")} </dt>
            <dd>
              {" "}
              {t(String(selected.metadata.channels))} {t("channels ·")}{" "}
              {t(String(selected.metadata.sample_rate))} {t("Hz")}{" "}
            </dd>
          </dl>
        </Modal>
      )}
      {deleteTarget && <AssetDeleteDialog asset={deleteTarget} onClose={() => setDeleteTarget(null)}
        onDeleted={(asset) => {
          setDeleteTarget(null); setDialog(null);
          setAssets((items) => items.filter((item) => item.id !== asset.id));
          if (selectedId === asset.id) setSelectedId(null);
          void loadAssets(); void refresh();
          notify(asset.deleted ? "Generation deleted permanently" : "Generation moved to Trash");
        }} />}
    </div>
  );
}
