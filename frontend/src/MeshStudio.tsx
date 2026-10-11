import { t, projectName } from "./i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Box,
  ChevronDown,
  Download,
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
import MeshViewer from "./MeshViewer";
import type {
  Asset,
  MeshRequest,
  MeshStats,
  MeshTexture,
  Snapshot,
  Job,
} from "./types";
import "./mesh.css";

const ACTIVE = new Set(["queued", "running"]);
const count = (value?: number) => (value || 0).toLocaleString();
const FORM_KEY = "atelier.mesh-draft";
const defaults = {
  prompt: "",
  seed: 42,
  resolution: 512,
  num_inference_steps: 12,
  texture_size: 2048,
  target_triangles: 30000,
  texture: true,
  background_removal: "auto" as "auto" | "birefnet",
};

export default function MeshStudio({
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
  notify: (s: string) => void;
  refresh: () => Promise<void>;
}) {
  const [form, setForm] = useState(() => {
    try {
      if (snapshot.status?.temporary) return defaults;
      return {
        ...defaults,
        ...JSON.parse(localStorage.getItem(FORM_KEY) || "{}"),
      } as typeof defaults;
    } catch {
      return defaults;
    }
  });
  const [mode, setMode] = useState<"image-to-3d" | "text-to-3d">("image-to-3d");
  const [reference, setReference] = useState<Asset | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<
    "images" | "export" | "simplify" | "details" | null
  >(null);
  const [images, setImages] = useState<Asset[]>([]);
  const [exporting, setExporting] = useState("");
  const [target, setTarget] = useState(10000);
  const [pendingJob, setPendingJob] = useState<string | null>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const meshInput = useRef<HTMLInputElement>(null);
  const currentFilter = useRef("");
  currentFilter.current = JSON.stringify([projectId, filter, query]);
  const model = snapshot.models.find((m) => m.id === "trellis2");
  const qwen = snapshot.models.find((m) => m.id === "qwen-image-2.1");
  const selected = assets.find((a) => a.id === selectedId) || assets[0] || null;
  const stats = selected?.metadata.stats as MeshStats | undefined;
  const textures = (selected?.metadata.textures || []) as MeshTexture[];
  const jobs = snapshot.jobs.filter(
    (j) => j.model_id === "trellis2" && j.project_id === projectId,
  );
  const active = jobs.filter((j) => ACTIVE.has(j.status));
  const latestError = jobs.find(
    (j) => j.status === "error" && Date.now() / 1000 - j.created < 3600,
  );
  const loadAssets = useCallback(async () => {
    const signature = JSON.stringify([projectId, filter, query]);
    try {
      const values = await api<Asset[]>(
        `/assets?${new URLSearchParams({ kind: "mesh", project: projectId, q: query, favorite: String(filter === "favorites"), trash: String(filter === "trash") })}`,
      );
      if (signature !== currentFilter.current) return;
      setAssets(values);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId, filter, query]);
  useEffect(() => {
    const timer = setTimeout(() => void loadAssets(), 150);
    return () => clearTimeout(timer);
  }, [loadAssets, snapshot.jobs]);
  useEffect(() => {
    if (snapshot.status?.temporary) return;
    localStorage.setItem(FORM_KEY, JSON.stringify(form));
  }, [form]);
  useEffect(() => {
    const source = new URLSearchParams(location.search).get("image");
    if (source)
      void api<Asset>(`/assets/${encodeURIComponent(source)}`)
        .then((asset) => {
          if (asset.kind !== "mesh") setReference(asset);
        })
        .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    const job = jobs.find((j) => j.id === pendingJob);
    if (job?.status === "complete") {
      setFilter("all");
      setQuery("");
      setSelectedId(job.result_ids[0]);
      setPendingJob(null);
      notify("Your 3D object is ready");
    } else if (job && !ACTIVE.has(job.status)) setPendingJob(null);
  }, [jobs, pendingJob, notify]);
  const setNumber = (key: keyof typeof defaults, value: string) =>
    setForm((f) => ({ ...f, [key]: Number(value) }));
  const uploadImage = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("image", file);
      body.append("project_id", projectId);
      setReference(await api<Asset>("/uploads", { method: "POST", body }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (imageInput.current) imageInput.current.value = "";
    }
  };
  const importMesh = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("mesh", file);
      body.append("project_id", projectId);
      const asset = await api<Asset>("/meshes/import", {
        method: "POST",
        body,
      });
      setFilter("all");
      setQuery("");
      await loadAssets();
      setSelectedId(asset.id);
      await refresh();
      notify("Mesh imported");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (meshInput.current) meshInput.current.value = "";
    }
  };
  const chooseImage = async () => {
    setDialog("images");
    setError("");
    try {
      setImages(await api<Asset[]>(`/assets?project=${projectId}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const submit = async (simplify = false) => {
    setBusy(true);
    setError("");
    try {
      const body: MeshRequest = {
        ...form,
        model_id: "trellis2",
        project_id: projectId,
        mode: simplify ? "simplify" : mode,
        reference_ids:
          !simplify && mode === "image-to-3d" && reference
            ? [reference.id]
            : [],
      };
      if (simplify && selected) {
        body.source_mesh_id = selected.id;
        body.target_triangles = target;
      }
      const job = await post<Job>("/meshes/jobs", body);
      setPendingJob(job.id);
      setDialog(null);
      await refresh();
      notify(simplify ? "Simplification queued" : "3D generation queued");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const changeAsset = async (changes: Record<string, unknown>) => {
    if (!selected) return;
    setError("");
    try {
      await patch(`/assets/${selected.id}`, changes);
      await loadAssets();
      await refresh();
      if (changes.deleted || changes.project_id) setDialog(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const download = async (format: string) => {
    if (!selected) return;
    setExporting(format);
    setError("");
    try {
      const response = await fetch(
        `/api/meshes/${selected.id}/export?format=${format}`,
      );
      if (!response.ok)
        throw new Error((await response.json()).error || "Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atelier-${selected.id.slice(0, 8)}.${["obj", "gltf", "textures"].includes(format) ? format + ".zip" : format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify(`${format.toUpperCase()} exported`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting("");
    }
  };
  const canGenerate =
    model?.status === "installed" &&
    !model.busy &&
    (mode === "image-to-3d"
      ? !!reference
      : form.prompt.trim() && qwen?.status === "installed" && !qwen.busy);
  return (
    <div className="page mesh-page">
      <header className="page-head">
        <div>
          <h1> {t("3D studio")} </h1>
          <p> {t("Shape an idea into something you can turn around.")} </p>
        </div>
        <select
          aria-label={t("3D project")}
          value={projectId}
          onChange={(e) => onProject(e.target.value)}
        >
          {snapshot.projects.map((p) => (
            <option key={p.id} value={p.id}>
              {" "}
              {projectName(p)}{" "}
            </option>
          ))}
        </select>
      </header>
      {error && (
        <div className="error-banner" role="alert">
          {" "}
          {t(error)}{" "}
          <button aria-label={t("Dismiss error")} onClick={() => setError("")}>
            <X size={17} />
          </button>
        </div>
      )}
      <div className="mesh-workspace">
        <form
          className="mesh-config"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="segmented mesh-modes">
            {(["image-to-3d", "text-to-3d"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={mode === value ? "active" : ""}
                onClick={() => setMode(value)}
              >
                {" "}
                {t(value === "image-to-3d" ? "Image to 3D" : "Text to 3D")}{" "}
              </button>
            ))}
          </div>
          {mode === "image-to-3d" ? (
            <div className="mesh-reference-section">
              <label> {t("Reference image")} </label>
              <div
                className="mesh-reference"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  void uploadImage(e.dataTransfer.files[0]);
                }}
              >
                <button
                  type="button"
                  className="mesh-reference-preview"
                  onClick={() => imageInput.current?.click()}
                  aria-label={t("Upload reference image")}
                >
                  {reference ? (
                    <img src={reference.thumbnail_url} alt={reference.name} />
                  ) : (
                    <>
                      <ImagePlus size={28} strokeWidth={1.3} />
                      <span> {t("Drop an image")} </span>
                    </>
                  )}
                </button>
                <div>
                  <button
                    className="secondary"
                    type="button"
                    onClick={() => imageInput.current?.click()}
                    disabled={busy}
                  >
                    <Upload size={15} /> {t("Choose image")}{" "}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => void chooseImage()}
                  >
                    <Folder size={15} /> {t("From project")}{" "}
                  </button>
                  {reference && (
                    <button
                      type="button"
                      className="text-link"
                      onClick={() => setReference(null)}
                    >
                      {" "}
                      {t("Remove image")}{" "}
                    </button>
                  )}
                </div>
              </div>
              <small>
                {" "}
                {t("One clear view of a single object works best.")}{" "}
              </small>
            </div>
          ) : (
            <div className="mesh-prompt">
              <label htmlFor="mesh-prompt"> {t("Describe your object")} </label>
              <textarea
                id="mesh-prompt"
                value={form.prompt}
                maxLength={4000}
                rows={5}
                onChange={(e) =>
                  setForm((f) => ({ ...f, prompt: e.target.value }))
                }
                placeholder={t(
                  "A burgundy ceramic teapot, rounded body, curved spout and a small lid…",
                )}
              />
              <small>
                {" "}
                {t(
                  "Qwen creates a reference image, then TRELLIS.2 builds the object. Both run locally.",
                )}{" "}
              </small>
              {qwen?.status !== "installed" && (
                <button
                  type="button"
                  className="text-link"
                  onClick={() => navigate("/models")}
                >
                  {" "}
                  {t("Install Qwen to use text prompts")}{" "}
                </button>
              )}
            </div>
          )}
          <div className="mesh-model">
            <label> {t("Model")} </label>
            <button type="button" onClick={() => navigate("/models")}>
              <span
                className={`status-dot ${model?.status === "installed" ? "ready" : ""}`}
              />
              <span>
                <strong>TRELLIS.2</strong>
                <small>
                  {" "}
                  {t(
                    model?.busy
                      ? model.operation?.phase
                      : model?.status === "installed"
                        ? "Ready · Q8"
                        : "Install in model library",
                  )}{" "}
                </small>
              </span>
              <ChevronDown size={14} />
            </button>
          </div>
          <div className="mesh-fields">
            <div className="mesh-field">
              <span> {t("Resolution")} </span>
              <div className="segmented">
                {[512, 1024].map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={form.resolution === n ? "active" : ""}
                    onClick={() => setForm((f) => ({ ...f, resolution: n }))}
                  >
                    {n}³
                  </button>
                ))}
              </div>
            </div>
            <label className="mesh-field">
              {" "}
              {t("Sampling steps")}{" "}
              <input
                aria-label={t("Sampling steps")}
                type="number"
                min={4}
                max={30}
                value={form.num_inference_steps}
                onChange={(e) =>
                  setNumber("num_inference_steps", e.target.value)
                }
              />
            </label>
            <label className="mesh-field">
              {" "}
              {t("Texture resolution")}{" "}
              <select
                aria-label={t("Texture resolution")}
                value={form.texture_size}
                disabled={!form.texture}
                onChange={(e) => setNumber("texture_size", e.target.value)}
              >
                {[512, 1024, 2048, 4096].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label className="mesh-field">
              {" "}
              {t("Target triangles")}{" "}
              <input
                aria-label={t("Target triangles")}
                type="number"
                min={1000}
                max={300000}
                step={1000}
                value={form.target_triangles}
                onChange={(e) => setNumber("target_triangles", e.target.value)}
              />
            </label>
            <label className="mesh-field">
              {" "}
              {t("Seed")}{" "}
              <div className="mesh-seed">
                <input
                  aria-label={t("Mesh seed")}
                  type="number"
                  min={0}
                  max={4294967295}
                  value={form.seed}
                  onChange={(e) => setNumber("seed", e.target.value)}
                />
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={t("Randomize mesh seed")}
                  onClick={() =>
                    setForm((f) => ({
                      ...f,
                      seed: crypto.getRandomValues(new Uint32Array(1))[0],
                    }))
                  }
                >
                  <RefreshCw size={14} />
                </button>
              </div>
            </label>
          </div>
          <details className="mesh-advanced">
            <summary> {t("More settings")} </summary>
            <label>
              <input
                type="checkbox"
                checked={form.texture}
                onChange={(e) =>
                  setForm((f) => ({ ...f, texture: e.target.checked }))
                }
              />{" "}
              {t("Generate PBR material")}{" "}
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.background_removal === "birefnet"}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    background_removal: e.target.checked ? "birefnet" : "auto",
                  }))
                }
              />{" "}
              {t("Remove background again")}{" "}
            </label>
            <p>
              {" "}
              {t(
                "512³ is the lighter option. 1024³ adds detail and takes longer. Triangle counts are targets; UV boundaries can limit simplification.",
              )}{" "}
            </p>
          </details>
          <button
            className="primary mesh-generate"
            type="submit"
            disabled={busy || !canGenerate}
          >
            {busy ? <LoaderCircle size={17} className="spin" /> : null}{" "}
            {t("Generate 3D")} <ArrowRight size={18} />
          </button>
        </form>
        <div className="mesh-center">
          <MeshViewer
            url={selected?.url}
            name={selected?.name}
            assetId={selected?.id}
            hasPreview={Boolean(selected?.metadata.preview_rendered)}
            caption={
              stats
                ? `${count(stats.triangles)} triangles · ${textures.length ? "PBR material" : "Geometry"}`
                : "TRELLIS.2 · Local generation"
            }
          />
          {active.map((job) => (
            <div className="mesh-job" key={job.id}>
              <div>
                <LoaderCircle className="spin" size={16} />
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
              <progress value={job.progress} max={100} />
              <small>
                {" "}
                {t(
                  job.status === "queued"
                    ? "Waiting for the GPU"
                    : "You can keep browsing while this runs.",
                )}{" "}
              </small>
            </div>
          ))}
          {latestError && !active.length && (
            <details className="mesh-job-error">
              <summary> {t("Last generation needs attention")} </summary>
              <p> {t(latestError.error)} </p>
            </details>
          )}
        </div>
        <aside className="mesh-assets">
          <div className="mesh-assets-head">
            <h2> {t("Project assets")} </h2>
            <button
              className="icon-btn"
              aria-label={t("Import GLB")}
              title={t("Import GLB (up to 64 MB)")}
              onClick={() => meshInput.current?.click()}
              disabled={busy}
            >
              <Plus size={19} />
            </button>
          </div>
          <div className="mesh-search">
            <Search size={14} />
            <input
              aria-label={t("Search meshes")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("Search objects")}
            />
          </div>
          <div className="mesh-filter">
            <button
              className={filter === "all" ? "active" : ""}
              onClick={() => setFilter("all")}
            >
              {" "}
              {t("All")}{" "}
            </button>
            <button
              aria-label={t("Favorite meshes")}
              className={filter === "favorites" ? "active" : ""}
              onClick={() => setFilter("favorites")}
            >
              <Star size={15} />
            </button>
            <button
              aria-label={t("Mesh trash")}
              className={filter === "trash" ? "active" : ""}
              onClick={() => setFilter("trash")}
            >
              <Trash2 size={15} />
            </button>
          </div>
          <div className="mesh-asset-list">
            {assets.map((asset) => (
              <button
                key={asset.id}
                className={`mesh-asset ${asset.id === selected?.id ? "selected" : ""}`}
                onClick={() => setSelectedId(asset.id)}
              >
                <img src={asset.thumbnail_url} alt="" />
                <span>{asset.name}</span>
                <small>
                  {" "}
                  {t(
                    count((asset.metadata.stats as MeshStats)?.triangles),
                  )}{" "}
                  {t("triangles")} {t(asset.favorite ? " · ★" : "")}{" "}
                </small>
              </button>
            ))}
            {!assets.length && (
              <div className="mesh-assets-empty">
                <Box size={25} strokeWidth={1.2} />
                <p>
                  {" "}
                  {t(
                    filter === "trash"
                      ? "Removed meshes appear here."
                      : filter === "favorites"
                        ? "Star an object to save it here."
                        : query
                          ? "No matching objects."
                          : "Your first object starts with an idea.",
                  )}{" "}
                </p>
                {filter === "all" && !query && (
                  <button
                    className="text-link"
                    onClick={() => meshInput.current?.click()}
                  >
                    {" "}
                    {t("Import a GLB")}{" "}
                  </button>
                )}
              </div>
            )}
          </div>
        </aside>
      </div>
      {selected ? (
        <footer className="mesh-result">
          <div>
            <button
              className="mesh-result-title"
              onClick={() => setDialog("details")}
            >
              <h2>{selected.name}</h2>
              <SlidersHorizontal size={15} />
            </button>
            <p>
              {selected.metadata.imported
                ? t("Imported mesh")
                : `TRELLIS.2 · ${selected.metadata.resolution || form.resolution}³ · Seed ${selected.seed}`}{" "}
              {t(
                selected.metadata.elapsed_seconds
                  ? ` · ${Math.round(Number(selected.metadata.elapsed_seconds))} s`
                  : "",
              )}{" "}
            </p>
          </div>
          <div className="mesh-result-actions">
            <button
              className="icon-btn"
              aria-label={t(
                selected.favorite ? "Unfavorite mesh" : "Favorite mesh",
              )}
              onClick={() => void changeAsset({ favorite: !selected.favorite })}
            >
              <Star
                size={19}
                fill={selected.favorite ? "currentColor" : "none"}
              />
            </button>
            {filter === "trash" ? (
              <button
                className="secondary"
                onClick={() => void changeAsset({ deleted: false })}
              >
                {" "}
                {t("Restore mesh")}{" "}
              </button>
            ) : (
              <>
                <button
                  className="secondary"
                  onClick={() => {
                    setTarget(
                      Math.max(
                        1000,
                        Math.floor((stats?.triangles || 30000) / 2000) * 1000,
                      ),
                    );
                    setDialog("simplify");
                  }}
                >
                  <SlidersHorizontal size={17} /> {t("Simplify")}{" "}
                </button>
                <div className="mesh-export-button">
                  <button
                    className="secondary"
                    disabled={!!exporting}
                    onClick={() => void download("glb")}
                  >
                    {exporting ? (
                      <LoaderCircle size={16} className="spin" />
                    ) : (
                      <Download size={16} />
                    )}{" "}
                    {t("Export GLB")}{" "}
                  </button>
                  <button
                    className="secondary"
                    aria-label={t("More export formats")}
                    onClick={() => setDialog("export")}
                  >
                    <ChevronDown size={17} />
                  </button>
                </div>
              </>
            )}
          </div>
        </footer>
      ) : (
        <div className="mesh-help">
          <Box size={17} />
          <p>
            {" "}
            {t(
              "Geometry, UVs and materials are saved together. Export to your favorite 3D tool when you’re ready.",
            )}{" "}
          </p>
        </div>
      )}
      <input
        hidden
        type="file"
        ref={imageInput}
        accept="image/png,image/jpeg,image/webp"
        onChange={(e) => void uploadImage(e.target.files?.[0])}
      />
      <input
        hidden
        type="file"
        ref={meshInput}
        accept=".glb"
        onChange={(e) => void importMesh(e.target.files?.[0])}
      />
      {dialog === "images" && (
        <Modal
          title={t("Choose a project image")}
          onClose={() => setDialog(null)}
          wide
        >
          <p className="mesh-dialog-note">
            {" "}
            {t(
              "Use a complete object with a clear silhouette. TRELLIS.2 takes one reference.",
            )}{" "}
          </p>
          <div className="mesh-image-picker">
            {images.map((image) => (
              <button
                key={image.id}
                onClick={() => {
                  setReference(image);
                  setDialog(null);
                }}
              >
                <img src={image.thumbnail_url} alt={image.name} />
                <span>{image.name}</span>
              </button>
            ))}
          </div>
          {!images.length && (
            <p className="mesh-dialog-note">
              {" "}
              {t(
                "This project has no generated images yet. Upload a reference or create one in Images.",
              )}{" "}
            </p>
          )}
        </Modal>
      )}
      {dialog === "export" && selected && (
        <Modal title={t("Export your object")} onClose={() => setDialog(null)}>
          <p className="mesh-dialog-note">
            {" "}
            {t(
              "GLB and glTF preserve the complete PBR material. STL and PLY are geometry exports.",
            )}{" "}
          </p>
          <div className="mesh-export-grid">
            {[
              ["glb", "GLB", "One file, textures included"],
              ["gltf", "glTF", "Scene + textures in a ZIP"],
              ["obj", "OBJ", "Mesh, MTL + texture maps"],
              ["stl", "STL", "Geometry for fabrication"],
              ["ply", "PLY", "Portable mesh geometry"],
              [
                "textures",
                "Texture maps",
                `${textures.length} original material maps`,
              ],
            ].map(([format, label, note]) => (
              <button
                key={format}
                className="mesh-export-option"
                disabled={
                  !!exporting || (format === "textures" && !textures.length)
                }
                onClick={() => void download(format)}
              >
                <strong>
                  {" "}
                  {t(exporting === format ? "Exporting…" : label)}{" "}
                </strong>
                <small> {t(note)} </small>
                <Download size={17} />
              </button>
            ))}
          </div>
          {error && (
            <p className="error-banner" role="alert">
              {" "}
              {t(error)}{" "}
            </p>
          )}
        </Modal>
      )}
      {dialog === "simplify" && selected && (
        <Modal
          title={t("Make a lighter version")}
          onClose={() => setDialog(null)}
        >
          <div className="mesh-dialog-body">
            <p>
              {" "}
              {t(
                "Reduce triangles while retaining UVs and materials. A separate version is saved; the original stays in your project.",
              )}{" "}
            </p>
            <label>
              {" "}
              {t("Target triangles")}{" "}
              <input
                aria-label={t("Simplified triangle target")}
                type="number"
                min={1000}
                max={Math.min(stats?.triangles || 300000, 300000)}
                step={1000}
                value={target}
                onChange={(e) => setTarget(Number(e.target.value))}
              />
            </label>
            <small>
              {" "}
              {t("Current mesh:")} {t(count(stats?.triangles))}{" "}
              {t(
                "triangles. Texture seams may keep the result above the target.",
              )}{" "}
            </small>
            {error && <p role="alert"> {t(error)} </p>}
            <button
              className="primary"
              disabled={
                busy || target < 1000 || target >= (stats?.triangles || 0)
              }
              onClick={() => void submit(true)}
            >
              {" "}
              {t("Save simplified version")} <ArrowRight size={17} />
            </button>
          </div>
        </Modal>
      )}
      {dialog === "details" && selected && (
        <Modal title={t("Object details")} onClose={() => setDialog(null)}>
          <div className="mesh-dialog-body">
            <label>
              {" "}
              {t("Name")}{" "}
              <input
                aria-label={t("Mesh name")}
                defaultValue={selected.name}
                key={selected.id}
                maxLength={120}
                onBlur={(e) => {
                  if (e.target.value.trim() && e.target.value !== selected.name)
                    void changeAsset({ name: e.target.value });
                }}
              />
            </label>
            <label>
              {" "}
              {t("Project")}{" "}
              <select
                value={selected.project_id}
                aria-label={t("Move mesh to project")}
                onChange={(e) =>
                  void changeAsset({ project_id: e.target.value })
                }
              >
                {snapshot.projects.map((p) => (
                  <option value={p.id} key={p.id}>
                    {" "}
                    {projectName(p)}{" "}
                  </option>
                ))}
              </select>
            </label>
            <dl className="mesh-stats">
              <div>
                <dt> {t("Triangles")} </dt>
                <dd> {t(count(stats?.triangles))} </dd>
              </div>
              <div>
                <dt> {t("Vertices")} </dt>
                <dd> {t(count(stats?.vertices))} </dd>
              </div>
              <div>
                <dt> {t("UV coordinates")} </dt>
                <dd> {t(stats?.has_uv ? "Included" : "None")} </dd>
              </div>
              <div>
                <dt> {t("Materials")} </dt>
                <dd>{stats?.materials || 0}</dd>
              </div>
            </dl>
            {selected.prompt && <p>{selected.prompt}</p>}
            <div className="mesh-textures">
              {textures.map((texture) => (
                <a
                  key={texture.name}
                  href={`/api/meshes/${selected.id}/textures/${texture.name}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    src={`/api/meshes/${selected.id}/textures/${texture.name}`}
                    alt={t(texture.channel)}
                  />
                  <span> {t(texture.channel)} </span>
                  <small>
                    {texture.width} × {texture.height}
                  </small>
                </a>
              ))}
            </div>
            <div className="mesh-details-actions">
              <a
                className="secondary"
                href={`/api/assets/${selected.id}/metadata`}
                target="_blank"
                rel="noreferrer"
              >
                {" "}
                {t("Generation metadata")}{" "}
              </a>
              <button
                className="quiet"
                onClick={() => void changeAsset({ deleted: !selected.deleted })}
              >
                <Trash2 size={16} />{" "}
                {t(selected.deleted ? "Restore" : "Move to trash")}{" "}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
