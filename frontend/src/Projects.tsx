import { t, projectName, assetCount } from "./i18n";
import { useEffect, useState, type FormEvent } from "react";
import {
  Archive,
  Folder,
  Image,
  Pencil,
  Plus,
  Search,
  Star,
  RotateCcw,
  ArrowUpRight,
} from "lucide-react";
import { api, patch, post, date } from "./api";
import { Empty, Modal } from "./ui";
import type { Project, Snapshot, Asset, Job } from "./types";

export function ProjectForm({
  project,
  onClose,
  onSave,
}: {
  project?: Project;
  onClose: () => void;
  onSave: (p: Project) => void;
}) {
  const [name, setName] = useState(project?.name || "");
  const [description, setDescription] = useState(project?.description || "");
  const [stylePrompt, setStylePrompt] = useState(project?.style_prompt || "");
  const [inherit, setInherit] = useState(project?.inherit_style !== 0);
  const [reference, setReference] = useState<string | null>(
    project?.style_reference_id || null,
  );
  const [concept, setConcept] = useState(
    t(
      "A character, an environment and a prop that demonstrate this visual style.",
    ),
  );
  const [referenceJob, setReferenceJob] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const p = project
        ? await patch<Project>(`/projects/${project.id}`, {
            name,
            description,
            style_prompt: stylePrompt,
            inherit_style: inherit,
            style_reference_id: reference,
          })
        : await post<Project>("/projects", {
            name,
            description,
            style_prompt: stylePrompt,
            inherit_style: inherit,
            style_reference_id: reference,
          });
      onSave(p);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!referenceJob) return;
    let stopped = false;
    const timer = setInterval(
      () =>
        void api<Job[]>("/jobs")
          .then((jobs) => {
            if (stopped) return;
            const job = jobs.find((j) => j.id === referenceJob);
            if (job?.status === "complete") {
              setReference(job.result_ids[0]);
              setReferenceJob(null);
              setGenerating(false);
            }
            if (
              job &&
              ["error", "cancelled", "interrupted"].includes(job.status)
            ) {
              setError(job.error || "Style reference generation stopped");
              setReferenceJob(null);
              setGenerating(false);
            }
          })
          .catch((e) => {
            if (!stopped) setError(e.message);
          }),
      2500,
    );
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [referenceJob]);
  const generateReference = async () => {
    if (!project) return;
    setGenerating(true);
    setError("");
    try {
      const job = await post<Job>("/jobs", {
        project_id: project.id,
        model_id: "qwen-image-2.1",
        prompt: concept + "\nArt direction: " + stylePrompt,
        use_style: false,
        use_style_reference: false,
        seed: Math.floor(Math.random() * 4294967295),
        width: 1024,
        height: 1024,
        num_inference_steps: 25,
      });
      setReferenceJob(job.id);
    } catch (e) {
      setGenerating(false);
      setError((e as Error).message);
    }
  };
  return (
    <Modal
      title={t(project ? "Edit project" : "New project")}
      onClose={onClose}
    >
      <form onSubmit={save} className="dialog-body form-stack">
        <label>
          {" "}
          {t("Project name")}{" "}
          <input
            autoFocus
            required
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("e.g. Material studies")}
          />
        </label>
        <label>
          {" "}
          {t("Description")} <span className="optional"> {t("optional")} </span>
          <textarea
            rows={3}
            value={description}
            maxLength={1000}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("What are you exploring?")}
          />
        </label>
        <fieldset className="project-style-fields">
          <legend> {t("Art direction")} </legend>
          <label>
            {" "}
            {t("Style prompt")}{" "}
            <textarea
              rows={3}
              maxLength={4000}
              value={stylePrompt}
              onChange={(e) => setStylePrompt(e.target.value)}
              placeholder={t(
                "e.g. 32 px pixel art, top-down view, muted woodland palette, crisp edges, consistent light from the upper left",
              )}
            />
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={inherit}
              onChange={(e) => setInherit(e.target.checked)}
            />{" "}
            {t("Use global style when this prompt is empty")}{" "}
          </label>
          <p>
            {" "}
            {t(
              "Applied to image generations in this project. You can switch the prompt or reference off for any image.",
            )}{" "}
          </p>
          {reference && (
            <div className="style-reference-preview">
              <img
                src={`/api/assets/${reference}/thumbnail`}
                alt={t("Project style reference")}
              />
              <button
                type="button"
                className="quiet"
                onClick={() => setReference(null)}
              >
                {" "}
                {t("Remove style reference")}{" "}
              </button>
            </div>
          )}
          <label>
            {" "}
            {t("Upload style reference")}{" "}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const body = new FormData();
                body.set("project_id", project?.id || "inbox");
                body.set("image", file);
                try {
                  const asset = await api<Asset>("/uploads", {
                    method: "POST",
                    body,
                  });
                  setReference(asset.id);
                } catch (error) {
                  setError((error as Error).message);
                }
              }}
            />
          </label>
          {project ? (
            <details>
              <summary> {t("Generate a style reference")} </summary>
              <label>
                {" "}
                {t("Reference concept")}{" "}
                <textarea
                  value={concept}
                  maxLength={4000}
                  onChange={(e) => setConcept(e.target.value)}
                />
              </label>
              <button
                className="secondary"
                type="button"
                disabled={generating || !concept.trim()}
                onClick={() => void generateReference()}
              >
                {" "}
                {t(
                  generating ? "Generating reference…" : "Generate with Qwen",
                )}{" "}
              </button>
              <p>
                {" "}
                {t(
                  "The result stays in this project. Save changes to make it the style reference.",
                )}{" "}
              </p>
            </details>
          ) : (
            <p>
              {" "}
              {t(
                "Create the project to generate a reference, or upload one now.",
              )}{" "}
            </p>
          )}
        </fieldset>
        {error ? (
          <p className="error" role="alert">
            {" "}
            {t(error)}{" "}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button className="secondary" type="button" onClick={onClose}>
            {" "}
            {t("Cancel")}{" "}
          </button>
          <button className="primary" disabled={busy || !name.trim()}>
            {" "}
            {t(
              busy ? "Saving…" : project ? "Save changes" : "Create project",
            )}{" "}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function Projects({
  snapshot,
  navigate,
  onOpenProject,
  refresh,
  notify,
  onNew,
}: {
  snapshot: Snapshot;
  navigate: (path: string, project?: string) => void;
  onOpenProject: (project: Project) => void;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
  onNew: () => void;
}) {
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const [archiveRows, setArchiveRows] = useState<Project[]>([]);
  const [edit, setEdit] = useState<Project | null>(null);
  const [error, setError] = useState("");
  const loadArchive = () =>
    api<Project[]>("/projects?archived=true")
      .then(setArchiveRows)
      .catch((e) => setError(e.message));
  useEffect(() => {
    if (archived) void loadArchive();
  }, [archived, snapshot.projects]);
  const change = async (p: Project, values: object, message: string) => {
    try {
      await patch(`/projects/${p.id}`, values);
      await refresh();
      if (archived) await loadArchive();
      notify(message);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const rows = (archived ? archiveRows : snapshot.projects).filter((p) =>
    (p.name + " " + p.description).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1> {t("Projects")} </h1>
          <p>
            {" "}
            {t(
              "A place for every idea, from first draft to finished asset.",
            )}{" "}
          </p>
        </div>
        <button className="primary" onClick={onNew}>
          <Plus size={18} /> {t("New project")}{" "}
        </button>
      </header>
      <div className="toolbar">
        <div className="search">
          <Search size={18} />
          <input
            aria-label={t("Search projects")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("Search projects")}
          />
        </div>
        <div className="segmented">
          <button
            className={!archived ? "active" : ""}
            onClick={() => setArchived(false)}
          >
            {" "}
            {t("Active")}{" "}
          </button>
          <button
            className={archived ? "active" : ""}
            onClick={() => setArchived(true)}
          >
            <Archive size={15} /> {t("Archived")}{" "}
          </button>
        </div>
      </div>
      {error ? (
        <div className="error-banner" role="alert">
          {" "}
          {t(error)}{" "}
        </div>
      ) : null}
      {rows.length ? (
        <div className="project-grid">
          {rows.map((p) => (
            <article key={p.id} className="project-card">
              <button
                className="project-cover"
                onClick={() => !archived && onOpenProject(p)}
                disabled={archived}
              >
                {p.cover_id ? (
                  <img
                    src={`/api/assets/${p.cover_id}/thumbnail`}
                    alt={t(`${projectName(p)} cover`)}
                  />
                ) : (
                  <Folder size={42} strokeWidth={1.1} />
                )}
                <span> {t(assetCount(p.asset_count || 0))} </span>
              </button>
              <div className="project-card-body">
                <div className="project-card-title">
                  <h2> {projectName(p)} </h2>
                  <button
                    className={`icon-btn ${p.favorite ? "favorited" : ""}`}
                    aria-label={t(
                      `${p.favorite ? "Unpin" : "Pin"} ${projectName(p)}`,
                    )}
                    onClick={() =>
                      void change(
                        p,
                        { favorite: !p.favorite },
                        p.favorite ? "Project unpinned" : "Project pinned",
                      )
                    }
                  >
                    <Star
                      size={17}
                      fill={p.favorite ? "currentColor" : "none"}
                    />
                  </button>
                </div>
                <p>
                  {p.description || t("A little space for your next idea.")}
                </p>
                {!archived && (
                  <div className="project-service-links">
                    <button
                      className="text-link"
                      onClick={() => navigate("/images", p.id)}
                    >
                      {" "}
                      {t("Images")}{" "}
                    </button>
                    <button
                      className="text-link"
                      onClick={() => navigate("/3d", p.id)}
                    >
                      {" "}
                      {t("3D objects")}{" "}
                    </button>
                    <button
                      className="text-link"
                      onClick={() => navigate("/video", p.id)}
                    >
                      {" "}
                      {t("Video studio")}{" "}
                    </button>
                  </div>
                )}
                <footer>
                  <span>
                    {" "}
                    {t("Updated")} {t(date(p.updated))}{" "}
                  </span>
                  <div>
                    <button
                      className="icon-btn"
                      aria-label={t(`Edit ${projectName(p)}`)}
                      onClick={() => setEdit(p)}
                    >
                      <Pencil size={16} />
                    </button>
                    {p.id !== "inbox" ? (
                      <button
                        className="icon-btn"
                        aria-label={t(
                          `${archived ? "Restore" : "Archive"} ${projectName(p)}`,
                        )}
                        onClick={() =>
                          void change(
                            p,
                            { archived: !archived },
                            archived
                              ? "Project restored"
                              : "Project archived; assets are kept",
                          )
                        }
                      >
                        {archived ? (
                          <RotateCcw size={16} />
                        ) : (
                          <Archive size={16} />
                        )}
                      </button>
                    ) : null}
                    {!archived ? (
                      <button
                        className="icon-btn"
                        aria-label={t(`Open ${projectName(p)}`)}
                        onClick={() => onOpenProject(p)}
                      >
                        <ArrowUpRight size={18} />
                      </button>
                    ) : null}
                  </div>
                </footer>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <Empty
          title={t(
            query
              ? "No matching projects"
              : archived
                ? "Nothing archived"
                : "Start a new project",
          )}
          description={t(
            query
              ? "Try another name."
              : "Keep related images, objects and ideas together.",
          )}
        >
          <button className="secondary" onClick={onNew}>
            <Image size={17} /> {t("Create project")}{" "}
          </button>
        </Empty>
      )}
      {edit ? (
        <ProjectForm
          project={edit}
          onClose={() => setEdit(null)}
          onSave={() => {
            setEdit(null);
            notify("Project updated");
            void refresh();
            if (archived) void loadArchive();
          }}
        />
      ) : null}
    </div>
  );
}
