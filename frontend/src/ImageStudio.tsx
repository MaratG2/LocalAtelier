import { t, projectName } from "./i18n";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowRight,
  ChevronDown,
  Download,
  Grid2X2,
  Image as ImageIcon,
  Link,
  List,
  LoaderCircle,
  Palette,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Shuffle,
  SlidersHorizontal,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { GameControls, GameToolSelect, GameWorkbench } from "./GameTools";
import { ProjectForm } from "./Projects";
import { api, date, patch, post } from "./api";
import { Empty, Modal } from "./ui";
import type { Asset, GameAsset, GenerationRequest, Snapshot } from "./types";

const ACTIVE = new Set(["queued", "running"]);
function initialDraft(project: string) {
  try {
    return JSON.parse(localStorage.getItem("atelier.draft." + project) || "{}");
  } catch {
    return {};
  }
}
function dimensions(ratio: string, size: number) {
  const [w, h] = ratio.split(":").map(Number);
  const scale = size / Math.max(w, h);
  return {
    width: Math.max(512, Math.round((w * scale) / 64) * 64),
    height: Math.max(512, Math.round((h * scale) / 64) * 64),
  };
}

function reducedRatio(width: number, height: number) {
  let a = width,
    b = height;
  while (b) [a, b] = [b, a % b];
  return `${width / a}:${height / a}`;
}

export function ImageStudio({
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
  navigate: (path: string) => void;
  notify: (s: string) => void;
  refresh: () => Promise<void>;
}) {
  const [draft] = useState(() =>
    snapshot.status?.temporary ? {} : initialDraft(projectId),
  );
  const [prompt, setPrompt] = useState<string>(draft.prompt || "");
  const [modelId, setModelId] = useState<string>(
    draft.modelId ||
      snapshot.models.find(
        (m) => m.service === "images" && m.status === "installed",
      )?.id ||
      "qwen-image-2.1",
  );
  const project = snapshot.projects.find((p) => p.id === projectId);
  const [useStyle, setUseStyle] = useState(true);
  const [useStyleReference, setUseStyleReference] = useState(true);
  const [gameAsset, setGameAsset] = useState<GameAsset | null>(null);
  const [workshop, setWorkshop] = useState<Asset | null>(null);
  const [editProject, setEditProject] = useState(false);
  const [settingsPanel, setSettingsPanel] = useState<"style" | "game" | null>(
    null,
  );
  const styleTrigger = useRef<HTMLButtonElement>(null);
  const gameTrigger = useRef<HTMLButtonElement>(null);
  const styleReference = useStyleReference ? project?.style_reference_id : null;
  const [mode, setMode] = useState<GenerationRequest["mode"]>("t2i");
  const [ratio, setRatio] = useState<string>(draft.ratio || "1:1");
  const [size, setSize] = useState<number>(draft.size || 1024);
  const [steps, setSteps] = useState<number>(draft.steps || 25);
  const [batch, setBatch] = useState(1);
  const [seed, setSeed] = useState<number>(draft.seed ?? 42);
  const [random, setRandom] = useState(true);
  const [keepAspect, setKeepAspect] = useState(true);
  const [transparent, setTransparent] = useState(false);
  const [pixel, setPixel] = useState(draft.pixel === true);
  const [pixelSize, setPixelSize] = useState<number>(
    [2, 4, 8, 16, 32].includes(draft.pixelSize) ? draft.pixelSize : 8,
  );
  const [pixelColors, setPixelColors] = useState<number>(
    Number.isInteger(draft.pixelColors) &&
      draft.pixelColors >= 2 &&
      draft.pixelColors <= 256
      ? draft.pixelColors
      : 32,
  );
  const [refs, setRefs] = useState<Asset[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [view, setView] = useState("grid");
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Asset | null>(null);
  const uploader = useRef<HTMLInputElement>(null);
  const promptInput = useRef<HTMLTextAreaElement>(null);
  const model = snapshot.models.find((m) => m.id === modelId);
  const jobs = snapshot.jobs.filter(
    (j) =>
      j.project_id === projectId &&
      !["trellis2", "vdn-h3"].includes(j.model_id),
  );
  const active = jobs.filter((j) => ACTIVE.has(j.status));
  const latest = jobs[0];
  const completedKey = jobs
    .map((j) => `${j.id}:${j.completed}:${j.status}`)
    .join("|");
  const activeFilter = useRef("");
  activeFilter.current = JSON.stringify([projectId, query, filter]);
  const loadAssets = useCallback(async () => {
    try {
      const signature = JSON.stringify([projectId, query, filter]);
      const search = new URLSearchParams({
        project: projectId,
        q: query,
        favorite: String(filter === "favorites"),
        trash: String(filter === "trash"),
      });
      const result = await api<Asset[]>("/assets?" + search);
      if (activeFilter.current === signature) setAssets(result);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId, query, filter]);
  useEffect(() => {
    const timer = setTimeout(() => void loadAssets(), 150);
    return () => clearTimeout(timer);
  }, [loadAssets, completedKey]);
  useEffect(() => {
    if (snapshot.status?.temporary) return;
    localStorage.setItem(
      "atelier.draft." + projectId,
      JSON.stringify({
        prompt,
        modelId,
        ratio,
        size,
        steps,
        seed,
        pixel,
        pixelSize,
        pixelColors,
      }),
    );
  }, [
    projectId,
    prompt,
    modelId,
    ratio,
    size,
    steps,
    seed,
    pixel,
    pixelSize,
    pixelColors,
    snapshot.status?.temporary,
  ]);
  const changeModel = (id: string) => {
    if (id === "manage") {
      navigate("/models");
      return;
    }
    setModelId(id);
    const next = snapshot.models.find((m) => m.id === id);
    setSteps(next?.steps || 25);
    if (!next?.transparent) setTransparent(false);
    setError("");
  };
  const changeMode = (next: GenerationRequest["mode"]) => {
    setMode(next);
    setUseStyleReference(false);
    if (next === "t2i") setRefs([]);
    if (next === "edit") setRefs((r) => r.slice(0, 1));
    setError("");
  };
  const upload = async (files: File[]) => {
    if (!files.length) return;
    setError("");
    if (files.length + refs.length > (model?.max_references || 10)) {
      setError(`Use up to ${model?.max_references || 10} references`);
      return;
    }
    setBusy(true);
    try {
      const uploaded: Asset[] = [];
      for (const file of files) {
        const body = new FormData();
        body.set("project_id", projectId);
        body.set("image", file);
        uploaded.push(await api<Asset>("/uploads", { method: "POST", body }));
      }
      const next = [...refs, ...uploaded];
      setRefs(next);
      setMode(next.length === 1 && mode !== "reference" ? "edit" : "reference");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const updateAsset = async (asset: Asset, values: object) => {
    try {
      const result = await patch<Asset>(`/assets/${asset.id}`, values);
      setSelected((current) => (current?.id === asset.id ? result : current));
      await loadAssets();
      void refresh();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  };
  const generate = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (pixel && !snapshot.status?.features?.includes("image-pixelation")) {
        throw new Error("Restart Local Atelier to use Pixel, then try again.");
      }
      const shape = dimensions(ratio, size);
      await post("/jobs", {
        project_id: projectId,
        model_id: modelId,
        mode,
        prompt,
        use_style: useStyle,
        use_style_reference: useStyleReference,
        game_asset: gameAsset,
        ...shape,
        seed: random ? Math.floor(Math.random() * (4294967295 - batch)) : seed,
        num_inference_steps: steps,
        batch_size: batch,
        reference_ids: mode === "t2i" ? [] : refs.map((r) => r.id),
        keep_original_aspect: mode !== "t2i" && keepAspect,
        transparent_background: transparent,
        ...(pixel
          ? { pixelation: { block_size: pixelSize, colors: pixelColors } }
          : {}),
      });
      await refresh();
      notify("Added to the generation queue");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const useImage = (asset: Asset) => {
    setRefs([asset]);
    setMode("edit");
    setUseStyleReference(false);
    setSelected(null);
    setPrompt("");
    promptInput.current?.focus();
    notify("Image added as an editing reference");
  };
  const reuse = async (asset: Asset) => {
    const settings = asset.metadata.settings;
    if (!settings) return;
    setPrompt(settings.user_prompt || settings.prompt);
    setUseStyle(settings.use_style ?? false);
    setUseStyleReference(false);
    setGameAsset(settings.game_asset || null);
    if (!settings.game_asset)
      setSettingsPanel((panel) => (panel === "game" ? null : panel));
    setModelId(settings.model_id);
    setSteps(settings.num_inference_steps);
    setSeed(settings.seed);
    setRandom(false);
    setSize(Math.max(settings.width, settings.height));
    setRatio(reducedRatio(settings.width, settings.height));
    setMode(settings.mode);
    setKeepAspect(settings.keep_original_aspect);
    setTransparent(settings.transparent_background);
    setPixel(!!settings.pixelation);
    setPixelSize(settings.pixelation?.block_size ?? 8);
    setPixelColors(settings.pixelation?.colors ?? 32);
    try {
      setRefs(
        await Promise.all(
          settings.reference_ids.map((id) => api<Asset>(`/assets/${id}`)),
        ),
      );
    } catch {
      setRefs([]);
      setMode("t2i");
    }
    setSelected(null);
    promptInput.current?.focus();
  };
  const disableGenerate =
    busy ||
    !prompt.trim() ||
    model?.status !== "installed" ||
    model?.busy ||
    (mode !== "t2i" && !refs.length && !styleReference) ||
    active.length >= 4;
  return (
    <div className="image-page">
      {editProject && (
        <ProjectForm
          project={project}
          onClose={() => setEditProject(false)}
          onSave={() => {
            setEditProject(false);
            void refresh();
          }}
        />
      )}
      {workshop && (
        <GameWorkbench asset={workshop} onClose={() => setWorkshop(null)} />
      )}
      <header className="page-head">
        <div>
          <h1> {t("Images")} </h1>
          <p> {t("Your ideas, rendered here.")} </p>
        </div>
        <label className="project-picker">
          <span className="sr-only"> {t("Current project")} </span>
          <select
            aria-label={t("Current project")}
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
        </label>
      </header>
      <div className="toolbar image-toolbar">
        <div className="search">
          <Search size={19} />
          <input
            aria-label={t("Search images")}
            placeholder={t("Search images")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="segmented">
          <button
            className={filter === "all" ? "active" : ""}
            onClick={() => setFilter("all")}
          >
            {" "}
            {t("All images")}{" "}
          </button>
          <button
            className={filter === "favorites" ? "active" : ""}
            onClick={() => setFilter("favorites")}
          >
            <Star size={16} /> {t("Favorites")}{" "}
          </button>
        </div>
        <div className="view-controls">
          <button
            className={`icon-btn ${filter === "trash" ? "selected" : ""}`}
            title={t("Trash")}
            aria-label={t("Show trashed images")}
            onClick={() => setFilter(filter === "trash" ? "all" : "trash")}
          >
            <Trash2 size={17} />
          </button>
          <button
            className={`icon-btn ${view === "grid" ? "selected" : ""}`}
            aria-label={t("Grid view")}
            onClick={() => setView("grid")}
          >
            <Grid2X2 size={18} />
          </button>
          <button
            className={`icon-btn ${view === "list" ? "selected" : ""}`}
            aria-label={t("List view")}
            onClick={() => setView("list")}
          >
            <List size={20} />
          </button>
        </div>
      </div>
      <div className="gallery-scroll">
        {active.length ? (
          <section className="job-list" aria-label={t("Generation queue")}>
            {active.map((j) => (
              <div className="job-card" key={j.id}>
                <div>
                  <LoaderCircle size={18} className="spin" />
                  <span>
                    <strong> {t(j.phase)} </strong>
                    <small>
                      {snapshot.models.find((m) => m.id === j.model_id)?.name} ·{" "}
                      {j.completed} {t("of")} {j.total} {t("complete")}{" "}
                    </small>
                  </span>
                  <button
                    className="quiet"
                    onClick={() => {
                      void post(`/jobs/${j.id}/cancel`)
                        .then(() => refresh())
                        .catch((e) => setError(e.message));
                    }}
                  >
                    {" "}
                    {t(
                      j.status === "queued" ? "Cancel" : "Stop after image",
                    )}{" "}
                  </button>
                </div>
                <div
                  className={`progress ${j.progress === 0 ? "indeterminate" : ""}`}
                >
                  <i style={{ width: `${j.progress || 20}%` }} />
                </div>
              </div>
            ))}
          </section>
        ) : null}
        {latest?.status === t("error") ? (
          <div className="error-banner job-error" role="alert">
            <div>
              <strong> {t("Generation did not finish")} </strong>
              <p> {t(latest.error)} </p>
            </div>
            <button className="text-link" onClick={() => navigate("/settings")}>
              {" "}
              {t("Diagnostics")}{" "}
            </button>
          </div>
        ) : null}
        {assets.length ? (
          <div
            className={`asset-gallery ${view === "list" ? "list-view" : ""}`}
          >
            {assets.map((asset) => (
              <article className="asset-card" key={asset.id}>
                <button
                  className="asset-image"
                  onClick={() => setSelected(asset)}
                >
                  <img
                    className={
                      asset.metadata.pixelation ? "pixel-preview" : undefined
                    }
                    src={asset.thumbnail_url}
                    alt={asset.prompt}
                    loading="lazy"
                  />
                </button>
                <div className="asset-caption">
                  <button
                    className="asset-name"
                    onClick={() => setSelected(asset)}
                  >
                    {asset.name}
                  </button>
                  <div>
                    <span>
                      {snapshot.models.find((m) => m.id === asset.model_id)
                        ?.name || asset.model_id}
                    </span>
                    <button
                      className={`icon-btn ${asset.favorite ? "favorited" : ""}`}
                      aria-label={t(
                        `${asset.favorite ? "Unfavorite" : "Favorite"} image ${asset.seed}`,
                      )}
                      onClick={() =>
                        void updateAsset(asset, { favorite: !asset.favorite })
                      }
                    >
                      <Star
                        size={16}
                        fill={asset.favorite ? "currentColor" : "none"}
                      />
                    </button>
                    {filter === "trash" ? (
                      <button
                        className="icon-btn"
                        aria-label={t(`Restore image ${asset.seed}`)}
                        onClick={() =>
                          void updateAsset(asset, { deleted: false })
                        }
                      >
                        <RotateCcw size={16} />
                      </button>
                    ) : (
                      <a
                        className="icon-btn"
                        aria-label={t(`Download image ${asset.seed}`)}
                        href={asset.url + "?download=true"}
                      >
                        <Download size={16} />
                      </a>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : active.length ? null : (
          <Empty
            title={t(
              filter === "trash"
                ? "Your trash is empty"
                : filter === "favorites"
                  ? "Keep your favorites close"
                  : query
                    ? "No matching images"
                    : "Your next idea starts here",
            )}
            description={t(
              filter === "trash"
                ? "Images you remove from a project can be restored here."
                : filter === "favorites"
                  ? "Star an image to find it here."
                  : query
                    ? "Try a different word from your prompt."
                    : "Describe an image below, or add a reference to start editing.",
            )}
          >
            {model?.status !== "installed" ? (
              <button className="secondary" onClick={() => navigate("/models")}>
                {" "}
                {t("Choose a model to install")}{" "}
              </button>
            ) : null}
          </Empty>
        )}
      </div>
      <form
        className="composer"
        onSubmit={generate}
        onKeyDown={(event) => {
          if (event.key === "Escape" && settingsPanel) {
            event.preventDefault();
            (settingsPanel === "style"
              ? styleTrigger
              : gameTrigger
            ).current?.focus();
            setSettingsPanel(null);
          }
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (!busy) void upload(Array.from(e.dataTransfer.files));
        }}
      >
        <div className="composer-top">
          <div
            className="mode-tabs"
            role="tablist"
            aria-label={t("Image task")}
          >
            {(
              [
                { id: "t2i", name: "Create", icon: ImageIcon },
                { id: "edit", name: "Edit", icon: Pencil },
                { id: "reference", name: "References", icon: Link },
              ] as const
            ).map(({ id, name, icon: Icon }) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={
                  (styleReference && mode !== "edit" ? "reference" : mode) ===
                  id
                }
                className={
                  (styleReference && mode !== "edit" ? "reference" : mode) ===
                  id
                    ? "active"
                    : ""
                }
                onClick={() => changeMode(id)}
              >
                <Icon size={17} /> {t(name)}{" "}
              </button>
            ))}
          </div>
          <div className={`composer-options${gameAsset ? " has-game" : ""}`}>
            <GameToolSelect
              value={gameAsset}
              onChange={(value) => {
                setGameAsset(value);
                setSettingsPanel(value ? "game" : null);
              }}
            />
            {gameAsset && (
              <button
                ref={gameTrigger}
                type="button"
                className="composer-option"
                aria-label={t("Game asset settings")}
                aria-expanded={settingsPanel === "game"}
                aria-controls="game-options"
                onClick={() =>
                  setSettingsPanel(settingsPanel === "game" ? null : "game")
                }
              >
                <Grid2X2 size={15} /> {gameAsset.columns} × {gameAsset.rows}
                <ChevronDown size={13} />
              </button>
            )}
            <button
              ref={styleTrigger}
              type="button"
              className="composer-option"
              aria-label={t("Style settings")}
              aria-expanded={settingsPanel === "style"}
              aria-controls="style-options"
              onClick={() =>
                setSettingsPanel(settingsPanel === "style" ? null : "style")
              }
            >
              {styleReference && mode !== "edit" ? (
                <img src={`/api/assets/${styleReference}/thumbnail`} alt="" />
              ) : (
                <Palette size={15} />
              )}
              {t(
                styleReference && mode !== "edit"
                  ? "Style: Reference"
                  : useStyle
                    ? "Style: Auto"
                    : "Style: Off",
              )}
              <ChevronDown size={13} />
            </button>
            {active.length ? (
              <span className="queue-count">
                {active.length} {t("in queue")}
              </span>
            ) : null}
          </div>
        </div>
        {settingsPanel && (
          <div
            className="composer-options-panel"
            id={settingsPanel === "style" ? "style-options" : "game-options"}
            role="region"
            aria-label={t(
              settingsPanel === "style"
                ? "Style settings"
                : "Game asset settings",
            )}
          >
            {settingsPanel === "game" && gameAsset ? (
              <GameControls value={gameAsset} onChange={setGameAsset} />
            ) : settingsPanel === "style" ? (
              <div className="style-controls">
                <div className="style-toggles">
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={useStyle}
                      onChange={(e) => setUseStyle(e.target.checked)}
                    />
                    {t("Project style")}
                  </label>
                  {project?.style_reference_id && (
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={useStyleReference && mode !== "edit"}
                        disabled={mode === "edit"}
                        onChange={(e) => setUseStyleReference(e.target.checked)}
                      />
                      {t("Style reference")}
                    </label>
                  )}
                </div>
                <p>
                  {styleReference && mode !== "edit"
                    ? t("References mode will be used")
                    : useStyle
                      ? project?.style_prompt ||
                        t("Use project or global art direction")
                      : t("Style prompt disabled for this image")}
                </p>
                <button
                  className="quiet"
                  type="button"
                  disabled={snapshot.status?.temporary}
                  onClick={() => setEditProject(true)}
                >
                  <Pencil size={14} /> {t("Edit style")}
                </button>
              </div>
            ) : null}
            <button
              type="button"
              className="icon-btn panel-close"
              aria-label={t("Close settings")}
              onClick={() => {
                (settingsPanel === "style"
                  ? styleTrigger
                  : gameTrigger
                ).current?.focus();
                setSettingsPanel(null);
              }}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {refs.length ? (
          <div className="reference-strip">
            {refs.map((ref, index) => (
              <div key={ref.id}>
                <img
                  src={ref.thumbnail_url}
                  alt={t(`Reference ${index + 1}`)}
                />
                <span>{index + 1}</span>
                <button
                  type="button"
                  aria-label={t(`Remove reference ${index + 1}`)}
                  onClick={() => setRefs(refs.filter((_, i) => i !== index))}
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            <p>
              {" "}
              {t(
                mode === "reference"
                  ? "Refer to image 1, image 2, and so on in your prompt."
                  : "Describe what you want to change in this image.",
              )}{" "}
            </p>
          </div>
        ) : null}
        <textarea
          ref={promptInput}
          aria-label={t("Image prompt")}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          maxLength={12000}
          rows={2}
          placeholder={t(
            mode === "t2i"
              ? "Describe what you want to create…"
              : mode === "edit"
                ? "What would you like to change?"
                : "Describe how to use your reference images…",
          )}
        />
        <div className="composer-controls">
          <button
            type="button"
            className="secondary add-references"
            onClick={() => uploader.current?.click()}
            disabled={busy}
          >
            <Plus size={19} /> {t("References")}{" "}
          </button>
          <input
            ref={uploader}
            type="file"
            className="sr-only"
            aria-label={t("Upload reference images")}
            accept="image/png,image/jpeg,image/webp"
            multiple
            onChange={(e) => {
              void upload(Array.from(e.target.files || []));
              e.target.value = "";
            }}
          />
          <label className="model-select">
            {" "}
            {t("Model")}{" "}
            <select
              aria-label={t("Image model")}
              value={modelId}
              onChange={(e) => changeModel(e.target.value)}
            >
              {snapshot.models
                .filter((m) => m.service === "images")
                .map((m) => (
                  <option
                    key={m.id}
                    value={m.id}
                    disabled={m.status !== "installed"}
                  >
                    {m.name}{" "}
                    {t(m.status !== "installed" ? " · not installed" : "")}{" "}
                  </option>
                ))}
              <option value="manage"> {t("Manage models…")} </option>
            </select>
          </label>
          <label>
            {" "}
            {t("Ratio")}{" "}
            <select
              aria-label={t("Aspect ratio")}
              value={ratio}
              disabled={!!gameAsset || (mode !== "t2i" && keepAspect)}
              onChange={(e) => setRatio(e.target.value)}
            >
              {["1:1", "4:3", "3:4", "16:9", "9:16"].map((r) => (
                <option key={r}> {t(r)} </option>
              ))}
              {!["1:1", "4:3", "3:4", "16:9", "9:16"].includes(ratio) ? (
                <option> {t(ratio)} </option>
              ) : null}
            </select>
          </label>
          <label>
            {" "}
            {t("Resolution")}{" "}
            <select
              aria-label={t("Resolution")}
              value={size}
              onChange={(e) => setSize(Number(e.target.value))}
            >
              <option value={1024}>1K</option>
              <option value={1536}>1.5K</option>
              <option value={2048}>2K</option>
            </select>
          </label>
          <label>
            {" "}
            {t("Steps")}{" "}
            <input
              aria-label={t("Steps")}
              type="number"
              min={1}
              max={model?.max_steps || 60}
              value={steps}
              onChange={(e) => setSteps(Number(e.target.value))}
            />
          </label>
          <label>
            {" "}
            {t("Batch")}{" "}
            <select
              aria-label={t("Batch size")}
              value={batch}
              onChange={(e) => setBatch(Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  ×{n}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary generate-button"
            disabled={disableGenerate}
          >
            {busy ? <LoaderCircle size={18} className="spin" /> : null}{" "}
            {t(busy ? "Preparing…" : "Generate")} <ArrowRight size={19} />
          </button>
        </div>
        <div className="composer-foot">
          <button
            type="button"
            className="quiet"
            aria-expanded={advanced}
            aria-controls="image-advanced-settings"
            onClick={() => setAdvanced(!advanced)}
          >
            <ChevronDown size={15} className={advanced ? "rotate" : ""} />{" "}
            {t("Advanced")}{" "}
          </button>
          {mode !== "t2i" ? (
            <label className="check-label">
              <input
                type="checkbox"
                checked={keepAspect}
                onChange={(e) => setKeepAspect(e.target.checked)}
              />{" "}
              {t("Keep reference aspect")}{" "}
            </label>
          ) : null}
          <div className="composer-output-options">
            <label
              className="check-label"
              title={t(
                !model?.transparent
                  ? "Native transparency is available with Qwen-Image-2.1"
                  : undefined,
              )}
            >
              <input
                type="checkbox"
                checked={transparent}
                disabled={!model?.transparent}
                onChange={(e) => setTransparent(e.target.checked)}
              />{" "}
              {t("Transparent background")}{" "}
            </label>
            <label
              className="check-label"
              title={t(
                "Pixelate the result after generation. Adjust pixel size and colors in Advanced.",
              )}
            >
              <input
                type="checkbox"
                checked={pixel}
                onChange={(e) => {
                  setPixel(e.target.checked);
                  if (e.target.checked) setAdvanced(true);
                }}
              />
              {t("Pixel")}
            </label>
          </div>
        </div>
        {advanced ? (
          <div className="advanced-controls" id="image-advanced-settings">
            <SlidersHorizontal size={18} />
            <label>
              {" "}
              {t("Seed")}{" "}
              <input
                aria-label={t("Seed")}
                type="number"
                min={0}
                max={4294967295}
                value={seed}
                disabled={random}
                onChange={(e) => setSeed(Number(e.target.value))}
              />
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={random}
                onChange={(e) => setRandom(e.target.checked)}
              />
              <Shuffle size={15} /> {t("Random seed")}{" "}
            </label>
            <p>
              {" "}
              {t(
                modelId === "hidream-o1"
                  ? "HiDream renders at its training scale, then exports at your selected size."
                  : "Start at 1K and 25 steps on a 16 GB GPU.",
              )}{" "}
            </p>
            {pixel && (
              <fieldset className="pixel-settings">
                <legend>{t("Pixel finish")}</legend>
                <div className="pixel-settings-controls">
                  <label>
                    {t("Pixel size")}
                    <select
                      aria-label={t("Pixel size")}
                      value={pixelSize}
                      onChange={(e) => setPixelSize(Number(e.target.value))}
                    >
                      {[2, 4, 8, 16, 32].map((value) => (
                        <option key={value} value={value}>
                          {t("{0} px", value)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("Colors")}
                    <select
                      aria-label={t("Colors")}
                      value={pixelColors}
                      onChange={(e) => setPixelColors(Number(e.target.value))}
                    >
                      {[...new Set([8, 16, 32, 64, 128, 256, pixelColors])]
                        .sort((a, b) => a - b)
                        .map((value) => (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        ))}
                    </select>
                  </label>
                  <p>
                    {t(
                      "Larger pixels simplify detail. Fewer colors reduce shading. Transparency uses hard edges.",
                    )}
                  </p>
                </div>
              </fieldset>
            )}
          </div>
        ) : null}
        {error ? (
          <div className="composer-error" role="alert">
            {" "}
            {t(error)}{" "}
            <button
              type="button"
              className="icon-btn"
              aria-label={t("Dismiss error")}
              onClick={() => setError("")}
            >
              <X size={16} />
            </button>
          </div>
        ) : null}
      </form>
      {selected ? (
        <Modal
          title={t("Image details")}
          wide
          onClose={() => setSelected(null)}
        >
          <div className="asset-detail">
            <div className="detail-preview">
              <img
                className={
                  selected.metadata.pixelation ? "pixel-preview" : undefined
                }
                src={selected.url}
                alt={selected.prompt}
              />
            </div>
            <div className="detail-info">
              <h3>{selected.name}</h3>
              {!!selected.metadata.game_asset && (
                <button
                  className="secondary"
                  onClick={() => {
                    setWorkshop(selected);
                    setSelected(null);
                  }}
                >
                  {" "}
                  {t("Open game asset workshop")}{" "}
                </button>
              )}
              {!snapshot.status?.temporary && (
                <button
                  className="secondary"
                  onClick={async () => {
                    try {
                      await patch(`/projects/${projectId}`, {
                        style_reference_id: selected.id,
                      });
                      setUseStyleReference(true);
                      setSelected(null);
                      notify("Project style reference updated");
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  {" "}
                  {t("Use as project style reference")}{" "}
                </button>
              )}
              <p>{selected.prompt}</p>
              <dl className="detail-list">
                <div>
                  <dt> {t("Model")} </dt>
                  <dd>
                    {
                      snapshot.models.find((m) => m.id === selected.model_id)
                        ?.name
                    }
                  </dd>
                </div>
                <div>
                  <dt> {t("Size")} </dt>
                  <dd>
                    {selected.width} × {selected.height}
                  </dd>
                </div>
                <div>
                  <dt> {t("Seed")} </dt>
                  <dd>{selected.seed}</dd>
                </div>
                <div>
                  <dt> {t("Created")} </dt>
                  <dd> {t(date(selected.created))} </dd>
                </div>
                {selected.metadata.elapsed_seconds ? (
                  <div>
                    <dt> {t("Generation time")} </dt>
                    <dd>
                      {selected.metadata.elapsed_seconds} {t("s")}{" "}
                    </dd>
                  </div>
                ) : null}
              </dl>
              <label>
                {" "}
                {t("Project")}{" "}
                <select
                  value={selected.project_id}
                  onChange={(e) =>
                    void updateAsset(selected, { project_id: e.target.value })
                  }
                >
                  {snapshot.projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {" "}
                      {projectName(p)}{" "}
                    </option>
                  ))}
                </select>
              </label>
              <div className="detail-actions">
                <a className="primary" href={selected.url + "?download=true"}>
                  <Download size={16} /> {t("Download PNG")}{" "}
                </a>
                <button
                  className="secondary"
                  onClick={() => useImage(selected)}
                  disabled={!!selected.deleted}
                >
                  <Pencil size={16} /> {t("Edit this image")}{" "}
                </button>
                {!selected.deleted && (
                  <>
                    <a
                      className="secondary"
                      href={`/3d?project=${selected.project_id}&image=${selected.id}`}
                      onClick={(event) => {
                        event.preventDefault();
                        navigate(event.currentTarget.getAttribute("href")!);
                      }}
                    >
                      {" "}
                      {t("Create a 3D object")}{" "}
                    </a>
                    <a
                      className="secondary"
                      href={`/video?project=${selected.project_id}&image=${selected.id}`}
                      onClick={(event) => {
                        event.preventDefault();
                        navigate(event.currentTarget.getAttribute("href")!);
                      }}
                    >
                      {" "}
                      {t("Animate image")}{" "}
                    </a>
                  </>
                )}
                <button
                  className="secondary"
                  onClick={() => void reuse(selected)}
                  disabled={!selected.metadata.settings || !!selected.deleted}
                >
                  <RotateCcw size={16} /> {t("Reuse settings")}{" "}
                </button>
                <a
                  className="quiet"
                  href={`/api/assets/${selected.id}/metadata`}
                  download={`atelier-${selected.seed}.json`}
                >
                  {" "}
                  {t("Download metadata")}{" "}
                </a>
                <button
                  className="quiet danger"
                  onClick={() => {
                    void updateAsset(selected, {
                      deleted: !selected.deleted,
                    }).then((ok) => {
                      if (ok) {
                        setSelected(null);
                        notify(
                          selected.deleted
                            ? "Image restored"
                            : "Image moved to trash",
                        );
                      }
                    });
                  }}
                >
                  {selected.deleted ? (
                    <RotateCcw size={16} />
                  ) : (
                    <Trash2 size={16} />
                  )}{" "}
                  {t(selected.deleted ? "Restore image" : "Move to trash")}{" "}
                </button>
              </div>
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
