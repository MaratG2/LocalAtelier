import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Camera, Grid2X2, Maximize, RotateCw, Box } from "lucide-react";

type ViewMode =
  | "material"
  | "clay"
  | "wireframe"
  | "base-color"
  | "roughness"
  | "metallic"
  | "normals";
type Viewer = {
  setMode: (mode: ViewMode) => void;
  grid: THREE.GridHelper;
  controls: OrbitControls;
  reset: () => void;
  capture: () => void;
};

export default function MeshViewer({
  url,
  name,
  caption,
  assetId,
  hasPreview,
}: {
  url?: string;
  name?: string;
  caption: string;
  assetId?: string;
  hasPreview?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef<Viewer | null>(null);
  const [mode, setMode] = useState<ViewMode>("material");
  const [grid, setGrid] = useState(true);
  const [rotate, setRotate] = useState(false);
  const [state, setState] = useState("empty");
  const [error, setError] = useState("");
  useEffect(() => {
    const element = host.current;
    if (!element || !url) {
      setState("empty");
      return;
    }
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false,
        preserveDrawingBuffer: true,
      });
    } catch {
      setState("error");
      setError(
        "WebGL is unavailable. Enable hardware acceleration to preview this model. Downloads still work.",
      );
      return;
    }
    let disposed = false;
    let frame = 0;
    setState("loading");
    setError("");
    setMode("material");
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#edf2ee");
    const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.domElement.setAttribute(
      "aria-label",
      `${name || "Mesh"}, interactive 3D preview`,
    );
    renderer.domElement.setAttribute("role", "img");
    renderer.domElement.tabIndex = 0;
    element.appendChild(renderer.domElement);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const environment = pmrem.fromScene(room, 0.04);
    scene.environment = environment.texture;
    room.dispose();
    pmrem.dispose();
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.minDistance = 1;
    controls.maxDistance = 12;
    controls.maxPolarAngle = Math.PI * 0.51;
    controls.autoRotateSpeed = 0.8;
    controls.listenToKeyEvents(renderer.domElement);
    const reset = () => {
      camera.position.set(2.8, 1.9, 3.5);
      controls.target.set(0, 0.8, 0);
      controls.update();
    };
    reset();
    const light = new THREE.DirectionalLight(0xffffff, 2.2);
    light.position.set(-3, 6, 4);
    light.castShadow = true;
    light.shadow.mapSize.set(1024, 1024);
    light.shadow.camera.left = -3;
    light.shadow.camera.right = 3;
    light.shadow.camera.top = 3;
    light.shadow.camera.bottom = -3;
    light.shadow.normalBias = 0.03;
    scene.add(light, new THREE.AmbientLight(0xffffff, 0.45));
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.ShadowMaterial({ opacity: 0.12 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.006;
    floor.receiveShadow = true;
    scene.add(floor);
    const ground = new THREE.GridHelper(12, 30, "#c6d4ca", "#dce5dc");
    ground.position.y = -0.012;
    scene.add(ground);
    const originals = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
    const overrides = new Set<THREE.Material>();
    const setViewMode = (next: ViewMode) => {
      for (const material of overrides) material.dispose();
      overrides.clear();
      originals.forEach((original, mesh) => {
        if (next === "material") {
          mesh.material = original;
          return;
        }
        const convert = (base: THREE.Material) => {
          const pbr = base as THREE.MeshStandardMaterial;
          let material: THREE.Material;
          if (next === "normals") material = new THREE.MeshNormalMaterial();
          else if (next === "clay" || next === "wireframe")
            material = new THREE.MeshStandardMaterial({
              color: "#abbfb0",
              roughness: 0.85,
              wireframe: next === "wireframe",
            });
          else {
            const map =
              next === "base-color"
                ? pbr.map
                : next === "roughness"
                  ? pbr.roughnessMap
                  : pbr.metalnessMap;
            material = new THREE.MeshBasicMaterial({
              map: map || null,
              color: next === "metallic" && !map ? 0x000000 : 0xffffff,
            });
            if (next === "roughness" || next === "metallic") {
              material.onBeforeCompile = (shader) => {
                shader.fragmentShader = shader.fragmentShader.replace(
                  "#include <map_fragment>",
                  `#include <map_fragment>\ndiffuseColor.rgb = vec3(diffuseColor.${next === "roughness" ? "g" : "b"});`,
                );
              };
            }
          }
          material.side = pbr.side;
          overrides.add(material);
          return material;
        };
        mesh.material = Array.isArray(original)
          ? original.map(convert)
          : convert(original);
      });
    };
    live.current = {
      setMode: setViewMode,
      grid: ground,
      controls,
      reset,
      capture: () => {
        renderer.render(scene, camera);
        renderer.domElement.toBlob((blob) => {
          if (!blob) return;
          const link = document.createElement("a");
          link.href = URL.createObjectURL(blob);
          link.download = "atelier-mesh-preview.png";
          link.click();
          setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        });
      },
    };
    const releaseObject = (object: THREE.Object3D) => {
      const textures = new Set<THREE.Texture>();
      object.traverse((item) => {
        if (!(item instanceof THREE.Mesh)) return;
        item.geometry.dispose();
        const material = originals.get(item) || item.material;
        for (const m of Array.isArray(material) ? material : [material]) {
          for (const value of Object.values(m))
            if (value instanceof THREE.Texture) textures.add(value);
          m.dispose();
        }
      });
      textures.forEach((texture) => texture.dispose());
    };
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (disposed) {
          releaseObject(gltf.scene);
          return;
        }
        const bounds = new THREE.Box3().setFromObject(gltf.scene);
        const center = bounds.getCenter(new THREE.Vector3());
        const size = bounds.getSize(new THREE.Vector3());
        const scale = 2 / Math.max(size.x, size.y, size.z, 0.001);
        gltf.scene.scale.multiplyScalar(scale);
        gltf.scene.position.set(
          -center.x * scale,
          -bounds.min.y * scale,
          -center.z * scale,
        );
        gltf.scene.traverse((item) => {
          if (item instanceof THREE.Mesh) {
            originals.set(item, item.material);
            item.castShadow = true;
            item.receiveShadow = true;
          }
        });
        scene.add(gltf.scene);
        setState("ready");
        if (assetId && !hasPreview)
          requestAnimationFrame(() => {
            if (disposed) return;
            renderer.render(scene, camera);
            const canvas = document.createElement("canvas");
            canvas.width = canvas.height = 512;
            const source = renderer.domElement;
            const side = Math.min(source.width, source.height);
            canvas
              .getContext("2d")
              ?.drawImage(
                source,
                (source.width - side) / 2,
                (source.height - side) / 2,
                side,
                side,
                0,
                0,
                512,
                512,
              );
            canvas.toBlob((blob) => {
              if (!blob || disposed) return;
              const body = new FormData();
              body.append("image", blob, "preview.png");
              void fetch(`/api/meshes/${assetId}/preview`, {
                method: "POST",
                body,
              }).catch(() => {});
            }, "image/png");
          });
      },
      undefined,
      (reason) => {
        if (!disposed) {
          setState("error");
          setError(
            reason instanceof Error
              ? reason.message
              : "This model could not be previewed",
          );
        }
      },
    );
    const resize = new ResizeObserver(() => {
      const { width, height } = element.getBoundingClientRect();
      if (width && height) {
        renderer.setSize(width, height);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      }
    });
    resize.observe(element);
    const draw = () => {
      frame = requestAnimationFrame(draw);
      controls.update();
      renderer.render(scene, camera);
    };
    draw();
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
      controls.dispose();
      live.current = null;
      releaseObject(scene);
      overrides.forEach((m) => m.dispose());
      environment.dispose();
      light.shadow.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [url, name]);
  useEffect(() => {
    live.current?.setMode(mode);
  }, [mode, state]);
  useEffect(() => {
    if (live.current) live.current.grid.visible = grid;
  }, [grid, state]);
  useEffect(() => {
    if (live.current) live.current.controls.autoRotate = rotate;
  }, [rotate, state]);
  return (
    <section className="mesh-viewport" aria-label="3D viewport">
      <div ref={host} className="mesh-canvas" />
      <div className="mesh-view-toolbar">
        <div className="segmented">
          {(["material", "clay", "wireframe"] as ViewMode[]).map((value) => (
            <button
              key={value}
              className={mode === value ? "active" : ""}
              onClick={() => setMode(value)}
              disabled={!url}
            >
              {value[0].toUpperCase() + value.slice(1)}
            </button>
          ))}
        </div>
        <div className="mesh-view-actions">
          <button
            className={`icon-btn ${grid ? "selected" : ""}`}
            title="Toggle ground grid"
            aria-label="Toggle ground grid"
            aria-pressed={grid}
            onClick={() => setGrid(!grid)}
          >
            <Grid2X2 size={17} />
          </button>
          <button
            className={`icon-btn ${rotate ? "selected" : ""}`}
            title="Auto rotate"
            aria-label="Auto rotate"
            aria-pressed={rotate}
            onClick={() => setRotate(!rotate)}
          >
            <RotateCw size={17} />
          </button>
          <button
            className="icon-btn"
            title="Reset view"
            aria-label="Reset view"
            onClick={() => live.current?.reset()}
          >
            <Maximize size={17} />
          </button>
          <button
            className="icon-btn"
            title="Save preview image"
            aria-label="Save preview image"
            disabled={state !== "ready"}
            onClick={() => live.current?.capture()}
          >
            <Camera size={17} />
          </button>
        </div>
      </div>
      {url && (
        <select
          className="mesh-channel"
          aria-label="Material channel"
          value={mode}
          onChange={(e) => setMode(e.target.value as ViewMode)}
        >
          <option value="material">PBR material</option>
          <option value="clay">Clay</option>
          <option value="wireframe">Wireframe</option>
          <option value="base-color">Base color</option>
          <option value="roughness">Roughness</option>
          <option value="metallic">Metallic</option>
          <option value="normals">Surface normals</option>
        </select>
      )}
      {state !== "ready" && (
        <div className="mesh-view-empty">
          <Box size={40} strokeWidth={1.1} />
          <h2>
            {state === "loading"
              ? "Opening your object…"
              : state === "error"
                ? "Preview unavailable"
                : "An idea, with another dimension"}
          </h2>
          <p>
            {state === "error"
              ? error
              : state === "loading"
                ? "Loading geometry and materials"
                : "Choose a reference image or describe an object to get started."}
          </p>
        </div>
      )}
      <div className="mesh-view-caption">
        <span>{caption}</span>
        <span>
          {state === "ready"
            ? "Drag to orbit · Scroll to zoom"
            : "Your mesh will appear here"}
        </span>
      </div>
      <span className="sr-only" role="status">
        {state === "ready" ? "3D model loaded" : ""}
      </span>
    </section>
  );
}
