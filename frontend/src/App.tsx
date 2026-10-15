import { t, projectName, LanguageSwitch, useLanguage } from "./i18n";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Home as HomeIcon,
  Image as ImageIcon,
  Folder,
  Layers,
  Box,
  Film,
  AudioLines,
  Settings as SettingsIcon,
  Monitor,
  Menu,
  X,
  Star,
  LockKeyhole,
} from "lucide-react";
import {
  PersonalBar,
  PersonalDialog,
  type PersonalAction,
} from "./PersonalSpace";
import { TemporaryMode } from "./TemporaryMode";
import { api, post, setWorkspace } from "./api";
import { Brand, Loading } from "./ui";
import { Home } from "./Home";
import { Projects, ProjectForm } from "./Projects";
import { ImageStudio } from "./ImageStudio";
import { ModelLibrary } from "./ModelLibrary";
import { Settings } from "./Settings";
import type { Asset, Project, Snapshot, Model, Job, Status } from "./types";
const MeshStudio = lazy(() => import("./MeshStudio"));
const VideoStudio = lazy(() => import("./VideoStudio"));

export default function App() {
  useLanguage();
  const [route, setRoute] = useState(location.pathname);
  const [projectId, setProjectId] = useState(
    new URLSearchParams(location.search).get("project") ||
      localStorage.getItem("atelier.project") ||
      "inbox",
  );
  const [snapshot, setSnapshot] = useState<Snapshot>({
    projects: [],
    models: [],
    jobs: [],
    status: null,
  });
  const [error, setError] = useState("");
  const [newProject, setNewProject] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [notice, setNotice] = useState("");
  const [personalDialog, setPersonalDialog] = useState<PersonalAction | null>(
    null,
  );
  const loadVersion = useRef(0);
  const navigationVersion = useRef(0);
  const load = useCallback(async () => {
    const version = ++loadVersion.current;
    try {
      const [projects, models, jobs, status] = await Promise.all([
        api<Project[]>("/projects"),
        api<Model[]>("/models"),
        api<Job[]>("/jobs"),
        api<Status>("/status"),
      ]);
      if (version !== loadVersion.current) return;
      setWorkspace(
        status.personal
          ? "personal"
          : status.temporary
            ? "temporary"
            : "public",
      );
      setSnapshot({ projects, models, jobs, status });
      setError("");
    } catch (e) {
      if (version !== loadVersion.current) return;
      setError(
        e instanceof Error ? e.message : "Cannot connect to Local Atelier",
      );
    }
  }, []);
  useEffect(() => {
    const clearPrivateScreen = () => {
      ++loadVersion.current;
      ++navigationVersion.current;
      setSnapshot({ projects: [], models: [], jobs: [], status: null });
      setNewProject(false);
      setPersonalDialog(null);
      setNotice("");
      setRoute("/settings");
      setProjectId("inbox");
    };
    window.addEventListener("atelier-space-locked", clearPrivateScreen);
    return () =>
      window.removeEventListener("atelier-space-locked", clearPrivateScreen);
  }, []);
  const spaceChanged = async (entered: boolean) => {
    ++loadVersion.current;
    ++navigationVersion.current;
    setWorkspace(undefined);
    setSnapshot({ projects: [], models: [], jobs: [], status: null });
    setNewProject(false);
    setNotice("");
    setProjectId("inbox");
    setMobileNav(false);
    const path = entered ? "/images" : "/settings";
    history.replaceState(null, "", path);
    setRoute(path);
    await load();
  };
  const lockPersonal = async () => {
    await post("/personal/lock");
    await spaceChanged(false);
  };
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await load();
      if (!stopped) timer = setTimeout(poll, 2500);
    };
    // A fresh document is a new session, including restored browser tabs.
    // Do not fetch a private gallery using a cookie restored by the browser.
    void post("/personal/lock")
      .then(() => {
        setWorkspace(undefined);
        if (!stopped) void poll();
      })
      .catch(() => {
        if (!stopped) void poll();
      });
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [load]);
  useEffect(() => {
    const pop = () => {
      ++navigationVersion.current;
      setRoute(location.pathname);
      setProjectId(
        new URLSearchParams(location.search).get("project") ||
          localStorage.getItem("atelier.project") ||
          "inbox",
      );
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  const navigate = (path: string, project?: string) => {
    ++navigationVersion.current;
    const destination = new URL(path, location.origin);
    if (project) destination.searchParams.set("project", project);
    const selectedProject = destination.searchParams.get("project");
    if (snapshot.status?.personal)
      history.replaceState(null, "", destination.pathname + destination.search);
    else history.pushState(null, "", destination.pathname + destination.search);
    setRoute(destination.pathname);
    if (selectedProject) {
      setProjectId(selectedProject);
      if (!snapshot.status?.temporary && !snapshot.status?.personal)
        localStorage.setItem("atelier.project", selectedProject);
    }
    setMobileNav(false);
  };
  const openProject = async (project: Project) => {
    const version = ++navigationVersion.current;
    try {
      const latest = project.cover_id
        ? await api<Asset>(`/assets/${encodeURIComponent(project.cover_id)}`)
        : null;
      // A later click or browser navigation takes precedence over this lookup.
      if (version !== navigationVersion.current) return;
      const path =
        latest?.kind === "video"
          ? "/video"
          : latest?.kind === "mesh"
            ? "/3d"
            : "/images";
      navigate(path, project.id);
    } catch (error) {
      if (version === navigationVersion.current)
        setError((error as Error).message);
    }
  };
  const currentProject =
    snapshot.projects.find((p) => p.id === projectId)?.id || "inbox";
  const pickProject = (id: string) => {
    ++navigationVersion.current;
    setProjectId(id);
    if (!snapshot.status?.temporary && !snapshot.status?.personal)
      localStorage.setItem("atelier.project", id);
    history.replaceState(null, "", `${route}?project=${id}`);
  };
  const notify = (message: string) => {
    setNotice(message);
    void load();
  };
  const nav = [
    { path: "/", label: "Home", icon: HomeIcon },
    { path: "/images", label: "Images", icon: ImageIcon },
    { path: "/3d", label: "3D studio", icon: Box },
    { path: "/video", label: "Video", icon: Film },
    { path: "/projects", label: "Projects", icon: Folder },
    { path: "/models", label: "Model library", icon: Layers },
  ];
  const gpu = snapshot.status?.hardware;
  return (
    <div className="app-shell">
      <div className="mobile-header">
        <Brand />
        <button
          className="icon-btn"
          aria-label={t("Toggle navigation")}
          onClick={() => setMobileNav(!mobileNav)}
        >
          {mobileNav ? <X /> : <Menu />}
        </button>
      </div>
      {mobileNav ? (
        <button
          className="nav-scrim"
          aria-label={t("Close navigation")}
          onClick={() => setMobileNav(false)}
        />
      ) : null}
      <aside className={`sidebar ${mobileNav ? "is-open" : ""}`}>
        <a
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate("/");
          }}
        >
          <Brand />
        </a>
        <nav aria-label={t("Main navigation")}>
          {nav.map(({ path, label, icon: Icon }) => (
            <a
              key={path}
              href={path}
              aria-current={route === path ? "page" : undefined}
              className={route === path ? "selected" : ""}
              onClick={(e) => {
                e.preventDefault();
                navigate(path);
              }}
            >
              <Icon size={21} strokeWidth={1.7} /> {t(label)}{" "}
            </a>
          ))}
        </nav>
        <div className="nav-section">
          <span className="section-label"> {t("Future tools")} </span>
          {[[AudioLines, "Audio"]].map(([Icon, label]) => {
            const I = Icon as typeof Box;
            return (
              <button
                key={String(label)}
                className="future-nav"
                onClick={() => {
                  setNotice(
                    `${label} is planned. Images, 3D and video are available now.`,
                  );
                  setMobileNav(false);
                }}
              >
                <I size={21} strokeWidth={1.7} />
                <span> {t(String(label))} </span>
                <small> {t("Later")} </small>
              </button>
            );
          })}
        </div>
        {snapshot.projects.some((p) => p.favorite) ? (
          <div className="nav-section favorites-nav">
            <span className="section-label"> {t("Pinned projects")} </span>
            {snapshot.projects
              .filter((p) => p.favorite)
              .slice(0, 4)
              .map((p) => (
                <button key={p.id} onClick={() => void openProject(p)}>
                  <Star size={15} />
                  <span> {projectName(p)} </span>
                </button>
              ))}
          </div>
        ) : null}
        <div className="sidebar-foot">
          <button
            className="personal-nav"
            disabled={!snapshot.status || snapshot.status.temporary}
            onClick={() => {
              if (snapshot.status?.personal) navigate("/settings");
              else
                setPersonalDialog(
                  snapshot.status?.personal_configured ? "unlock" : "setup",
                );
              setMobileNav(false);
            }}
          >
            <LockKeyhole size={19} strokeWidth={1.7} />
            {t("Personal space")}
          </button>
          <LanguageSwitch />
          <div
            className="gpu-small"
            title={t(gpu?.gpu_name || "No NVIDIA GPU detected")}
          >
            <Monitor size={18} />
            <span>
              {" "}
              {t(
                gpu?.gpu_name
                  ? gpu.gpu_name.replace("NVIDIA GeForce ", "")
                  : "GPU not detected",
              )}{" "}
              {t(
                gpu?.gpu_total_mib
                  ? ` · ${Math.round(gpu.gpu_total_mib / 1024)} GB`
                  : "",
              )}{" "}
            </span>
            <i className={gpu?.gpu_name ? "online" : ""} />
          </div>
          <a
            href="/settings"
            className={route === "/settings" ? "selected" : ""}
            onClick={(e) => {
              e.preventDefault();
              navigate("/settings");
            }}
          >
            <SettingsIcon size={21} strokeWidth={1.7} /> {t("Settings")}{" "}
          </a>
        </div>
      </aside>
      <main
        key={String(snapshot.status?.personal)}
        className={`main ${route === "/images" ? "studio-main" : ""}`}
      >
        {snapshot.status?.personal ? (
          <PersonalBar onLock={lockPersonal} />
        ) : (
          <TemporaryMode
            snapshot={snapshot}
            changed={async () => {
              setWorkspace(undefined);
              await load();
            }}
          />
        )}
        {snapshot.status?.cleanup_error && (
          <p className="error-banner" role="alert">
            {" "}
            {t(snapshot.status.cleanup_error)}{" "}
          </p>
        )}
        {error ? (
          <div className="error-banner" role="alert">
            {" "}
            {t(error)}{" "}
            <button onClick={() => void load()}> {t("Retry")} </button>
          </div>
        ) : null}
        {!snapshot.status && !error ? (
          <Loading />
        ) : route === "/" ? (
          <Home
            snapshot={snapshot}
            navigate={navigate}
            onOpenProject={openProject}
            onNewProject={() => setNewProject(true)}
          />
        ) : route === "/projects" ? (
          <Projects
            snapshot={snapshot}
            navigate={navigate}
            onOpenProject={openProject}
            refresh={load}
            notify={notify}
            onNew={() => setNewProject(true)}
          />
        ) : route === "/images" ? (
          <ImageStudio
            key={currentProject + String(snapshot.status?.temporary)}
            snapshot={snapshot}
            projectId={currentProject}
            onProject={pickProject}
            navigate={navigate}
            notify={notify}
            refresh={load}
          />
        ) : route === "/3d" ? (
          <Suspense fallback={<Loading />}>
            <MeshStudio
              key={currentProject + String(snapshot.status?.temporary)}
              snapshot={snapshot}
              projectId={currentProject}
              onProject={pickProject}
              navigate={navigate}
              notify={notify}
              refresh={load}
            />
          </Suspense>
        ) : route === "/video" ? (
          <Suspense fallback={<Loading />}>
            <VideoStudio
              key={currentProject + String(snapshot.status?.temporary)}
              snapshot={snapshot}
              projectId={currentProject}
              onProject={pickProject}
              navigate={navigate}
              notify={notify}
              refresh={load}
            />
          </Suspense>
        ) : route === "/models" ? (
          <ModelLibrary snapshot={snapshot} refresh={load} notify={notify} />
        ) : route === "/settings" ? (
          <Settings
            snapshot={snapshot}
            refresh={load}
            notify={notify}
            onPersonal={setPersonalDialog}
            onLock={lockPersonal}
          />
        ) : (
          <div className="empty">
            <h1> {t("Page not found")} </h1>
            <button className="primary" onClick={() => navigate("/")}>
              {" "}
              {t("Back to home")}{" "}
            </button>
          </div>
        )}
      </main>
      {notice ? (
        <div className="toast" role="status">
          {" "}
          {t(notice)}{" "}
          <button
            aria-label={t("Dismiss notification")}
            onClick={() => setNotice("")}
          >
            <X size={16} />
          </button>
        </div>
      ) : null}
      {newProject ? (
        <ProjectForm
          onClose={() => setNewProject(false)}
          onSave={(p) => {
            setNewProject(false);
            ++loadVersion.current;
            setSnapshot((previous) => ({
              ...previous,
              projects: [
                p,
                ...previous.projects.filter((item) => item.id !== p.id),
              ],
            }));
            notify("Project created");
            navigate("/images", p.id);
          }}
        />
      ) : null}
      {personalDialog && (
        <PersonalDialog
          mode={personalDialog}
          onClose={() => setPersonalDialog(null)}
          onComplete={async (entered) => {
            if (entered) await spaceChanged(true);
            else {
              notify("Personal password changed");
              await load();
            }
          }}
        />
      )}
    </div>
  );
}
