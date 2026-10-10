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
import type { Project, Snapshot } from "./types";

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const p = project
        ? await patch<Project>(`/projects/${project.id}`, { name, description })
        : await post<Project>("/projects", { name, description });
      onSave(p);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={project ? "Edit project" : "New project"} onClose={onClose}>
      <form onSubmit={save} className="dialog-body form-stack">
        <label>
          Project name
          <input
            autoFocus
            required
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Material studies"
          />
        </label>
        <label>
          Description <span className="optional">optional</span>
          <textarea
            rows={3}
            value={description}
            maxLength={1000}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What are you exploring?"
          />
        </label>
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button className="secondary" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : project ? "Save changes" : "Create project"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function Projects({
  snapshot,
  navigate,
  refresh,
  notify,
  onNew,
}: {
  snapshot: Snapshot;
  navigate: (path: string, project?: string) => void;
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
          <h1>Projects</h1>
          <p>A place for every idea, from first draft to finished asset.</p>
        </div>
        <button className="primary" onClick={onNew}>
          <Plus size={18} />
          New project
        </button>
      </header>
      <div className="toolbar">
        <div className="search">
          <Search size={18} />
          <input
            aria-label="Search projects"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects"
          />
        </div>
        <div className="segmented">
          <button
            className={!archived ? "active" : ""}
            onClick={() => setArchived(false)}
          >
            Active
          </button>
          <button
            className={archived ? "active" : ""}
            onClick={() => setArchived(true)}
          >
            <Archive size={15} />
            Archived
          </button>
        </div>
      </div>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {rows.length ? (
        <div className="project-grid">
          {rows.map((p) => (
            <article key={p.id} className="project-card">
              <button
                className="project-cover"
                onClick={() => !archived && navigate("/images", p.id)}
                disabled={archived}
              >
                {p.cover_id ? (
                  <img
                    src={`/api/assets/${p.cover_id}/thumbnail`}
                    alt={`${p.name} cover`}
                  />
                ) : (
                  <Folder size={42} strokeWidth={1.1} />
                )}
                <span>{p.asset_count || 0} assets</span>
              </button>
              <div className="project-card-body">
                <div className="project-card-title">
                  <h2>{p.name}</h2>
                  <button
                    className={`icon-btn ${p.favorite ? "favorited" : ""}`}
                    aria-label={`${p.favorite ? "Unpin" : "Pin"} ${p.name}`}
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
                <p>{p.description || "A little space for your next idea."}</p>
                {!archived && (
                  <div className="project-service-links">
                    <button
                      className="text-link"
                      onClick={() => navigate("/images", p.id)}
                    >
                      Images
                    </button>
                    <button
                      className="text-link"
                      onClick={() => navigate("/3d", p.id)}
                    >
                      3D objects
                    </button>
                  </div>
                )}
                <footer>
                  <span>Updated {date(p.updated)}</span>
                  <div>
                    <button
                      className="icon-btn"
                      aria-label={`Edit ${p.name}`}
                      onClick={() => setEdit(p)}
                    >
                      <Pencil size={16} />
                    </button>
                    {p.id !== "inbox" ? (
                      <button
                        className="icon-btn"
                        aria-label={`${archived ? "Restore" : "Archive"} ${p.name}`}
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
                        aria-label={`Open ${p.name}`}
                        onClick={() => navigate("/images", p.id)}
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
          title={
            query
              ? "No matching projects"
              : archived
                ? "Nothing archived"
                : "Start a new project"
          }
          description={
            query
              ? "Try another name."
              : "Keep related images, objects and ideas together."
          }
        >
          <button className="secondary" onClick={onNew}>
            <Image size={17} />
            Create project
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
            if (archived) void loadArchive();
          }}
        />
      ) : null}
    </div>
  );
}
