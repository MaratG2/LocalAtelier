import { t, projectName, assetCount } from "./i18n";
import {
  ArrowRight,
  Plus,
  Image,
  Box,
  Film,
  AudioLines,
  Folder,
  ChevronRight,
} from "lucide-react";
import type { Project, Snapshot } from "./types";
export function Home({
  snapshot,
  navigate,
  onOpenProject,
  onNewProject,
}: {
  snapshot: Snapshot;
  navigate: (path: string, project?: string) => void;
  onOpenProject: (project: Project) => void;
  onNewProject: () => void;
}) {
  return (
    <div className="page home-page">
      <header className="page-head">
        <div>
          <h1> {t("Your creative workspace")} </h1>
          <p>
            {" "}
            {t(
              "Make something worth keeping. Everything stays on your machine.",
            )}{" "}
          </p>
        </div>
        <button className="secondary" onClick={onNewProject}>
          <Plus size={17} /> {t("New project")}{" "}
        </button>
      </header>
      <section className="home-feature">
        <div className="feature-copy">
          <div className="feature-symbol">
            <Image size={29} strokeWidth={1.6} />
          </div>
          <h2> {t("A thought. An image.")} </h2>
          <p>
            {" "}
            {t(
              "Create, edit and combine references with models running on your GPU.",
            )}{" "}
          </p>
          <button className="primary" onClick={() => navigate("/images")}>
            {" "}
            {t("Open image studio")} <ArrowRight size={18} />
          </button>
        </div>
        <img
          src="/atelier-vase.png"
          alt={t(
            "Sculptural green ceramic vase with a leafy branch in soft sunlight",
          )}
        />
      </section>
      <div className="future-services">
        {[
          {
            name: "3D studio",
            icon: Box,
            description:
              "Turn an image or idea into a textured object with TRELLIS.2.",
          },
          {
            name: "Video",
            icon: Film,
            description: "Create video and stereo sound with MiniMax H3.",
          },
          {
            name: "Audio",
            icon: AudioLines,
            description: "Create and edit audio with local models.",
          },
        ].map(({ name, icon: Icon, description }) => (
          <section key={name}>
            <div className="service-icon">
              <Icon size={27} strokeWidth={1.6} />
            </div>
            <div>
              <div className="service-title">
                <h3> {t(name)} </h3>
                {name === "3D studio" || name === "Video" ? (
                  <button
                    className="text-link"
                    onClick={() =>
                      navigate(name === "Video" ? "/video" : "/3d")
                    }
                  >
                    {" "}
                    {t("Open studio")} <ArrowRight size={15} />
                  </button>
                ) : (
                  <span className="badge muted"> {t("Planned")} </span>
                )}
              </div>
              <p> {t(description)} </p>
            </div>
          </section>
        ))}
      </div>
      <div className="home-lower">
        <section className="surface">
          <div className="section-head">
            <h2> {t("Recent projects")} </h2>
            <button className="text-link" onClick={() => navigate("/projects")}>
              {" "}
              {t("View all")}{" "}
            </button>
          </div>
          <div className="recent-projects">
            {snapshot.projects.slice(0, 3).map((p) => (
              <button
                className="project-row"
                key={p.id}
                onClick={() => onOpenProject(p)}
              >
                {p.cover_id ? (
                  <img src={`/api/assets/${p.cover_id}/thumbnail`} alt="" />
                ) : (
                  <div className="project-placeholder">
                    <Folder size={24} />
                  </div>
                )}
                <span>
                  <strong> {projectName(p)} </strong>
                  <small> {t(assetCount(p.asset_count || 0))} </small>
                </span>
                <ChevronRight size={17} />
              </button>
            ))}
          </div>
          <button className="new-project-row" onClick={onNewProject}>
            <Plus size={18} /> {t("New project")}{" "}
          </button>
        </section>
        <section className="surface">
          <div className="section-head">
            <h2> {t("Your models")} </h2>
            <button className="text-link" onClick={() => navigate("/models")}>
              {" "}
              {t("Manage models")}{" "}
            </button>
          </div>
          <div className="model-rows">
            {snapshot.models.map((m) => (
              <button
                className="model-row"
                key={m.id}
                onClick={() => navigate("/models")}
              >
                <strong>{m.name}</strong>
                <span
                  className={`model-state ${m.status === "installed" ? "ready" : ""}`}
                >
                  <i />{" "}
                  {t(
                    m.busy
                      ? m.operation?.phase
                      : m.status === "installed"
                        ? "Installed"
                        : "Not installed",
                  )}{" "}
                </span>
                <small>
                  {m.vram_gb} {t("GB profile")}{" "}
                </small>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
