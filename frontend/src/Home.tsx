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
import type { Snapshot } from "./types";
export function Home({
  snapshot,
  navigate,
  onNewProject,
}: {
  snapshot: Snapshot;
  navigate: (path: string, project?: string) => void;
  onNewProject: () => void;
}) {
  return (
    <div className="page home-page">
      <header className="page-head">
        <div>
          <h1>Your creative workspace</h1>
          <p>Make something worth keeping. Everything stays on your machine.</p>
        </div>
        <button className="secondary" onClick={onNewProject}>
          <Plus size={17} />
          New project
        </button>
      </header>
      <section className="home-feature">
        <div className="feature-copy">
          <div className="feature-symbol">
            <Image size={29} strokeWidth={1.6} />
          </div>
          <h2>A thought. An image.</h2>
          <p>
            Create, edit and combine references with models running on your GPU.
          </p>
          <button className="primary" onClick={() => navigate("/images")}>
            Open image studio
            <ArrowRight size={18} />
          </button>
        </div>
        <img
          src="/atelier-vase.png"
          alt="Sculptural green ceramic vase with a leafy branch in soft sunlight"
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
            description: "Turn ideas into video using local models.",
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
                <h3>{name}</h3>
                {name === "3D studio" ? (
                  <button className="text-link" onClick={() => navigate("/3d")}>
                    Open studio <ArrowRight size={15} />
                  </button>
                ) : (
                  <span className="badge muted">Planned</span>
                )}
              </div>
              <p>{description}</p>
            </div>
          </section>
        ))}
      </div>
      <div className="home-lower">
        <section className="surface">
          <div className="section-head">
            <h2>Recent projects</h2>
            <button className="text-link" onClick={() => navigate("/projects")}>
              View all
            </button>
          </div>
          <div className="recent-projects">
            {snapshot.projects.slice(0, 3).map((p) => (
              <button
                className="project-row"
                key={p.id}
                onClick={() => navigate("/images", p.id)}
              >
                {p.cover_id ? (
                  <img src={`/api/assets/${p.cover_id}/thumbnail`} alt="" />
                ) : (
                  <div className="project-placeholder">
                    <Folder size={24} />
                  </div>
                )}
                <span>
                  <strong>{p.name}</strong>
                  <small>
                    {p.asset_count || 0}{" "}
                    {(p.asset_count || 0) === 1 ? "asset" : "assets"}
                  </small>
                </span>
                <ChevronRight size={17} />
              </button>
            ))}
          </div>
          <button className="new-project-row" onClick={onNewProject}>
            <Plus size={18} />
            New project
          </button>
        </section>
        <section className="surface">
          <div className="section-head">
            <h2>Your models</h2>
            <button className="text-link" onClick={() => navigate("/models")}>
              Manage models
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
                  <i />
                  {m.busy
                    ? m.operation?.phase
                    : m.status === "installed"
                      ? "Installed"
                      : "Not installed"}
                </span>
                <small>{m.vram_gb} GB profile</small>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
