import { t } from "./i18n";
import { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  Footprints,
  Grid2X2,
  Image as ImageIcon,
  Pause,
  PencilLine,
  Play,
  Rotate3D,
  Swords,
  Undo2,
  Wind,
} from "lucide-react";
import { Modal } from "./ui";
import { studioFetch } from "./api";
import type { Asset, GameAsset } from "./types";

export const defaultGameAsset: GameAsset = {
  kind: "spritesheet",
  columns: 4,
  rows: 1,
  cell_size: 64,
  fps: 8,
  generation: "individual",
  count: 4,
  action: "idle",
  direction: "right",
  custom_frames: [],
  seamless: true,
};
export function normalizeGameAsset(value: GameAsset): GameAsset {
  const result = {
    ...defaultGameAsset,
    ...value,
    generation: "individual" as const,
  };
  result.action =
    value.action || (value.kind === "tileset" ? "variations" : "idle");
  result.custom_frames = (
    result.action === "custom" ? value.custom_frames || [] : []
  )
    .map((s) => s.trim())
    .filter(Boolean);
  result.count =
    result.action === "views"
      ? 4
      : result.action === "custom"
        ? result.custom_frames.length
        : value.count || 4;
  result.columns = Math.min(4, Math.max(1, result.count));
  result.rows = Math.max(1, Math.ceil(result.count / 4));
  delete result.pixel_art;
  delete result.palette;
  return result;
}
export const presetName = (action: GameAsset["action"]) =>
  ({
    idle: "Idle",
    walk: "Walk",
    attack: "Attack",
    views: "Four views",
    custom: "Custom frames",
    variations: "Material variations",
  })[action || "idle"];

export function GameToolSelect({
  value,
  onChange,
}: {
  value: GameAsset | null;
  onChange: (v: GameAsset | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const choices = [
    {
      id: "image",
      name: "Image",
      icon: ImageIcon,
      description: "Create, edit or combine images with references.",
    },
    {
      id: "spritesheet",
      name: "Character sheet",
      icon: Footprints,
      description: "Idle, walk, attack and custom animation frames.",
    },
    {
      id: "tileset",
      name: "Tiles & textures",
      icon: Grid2X2,
      description: "Repeating materials, tile variations and a map workshop.",
    },
  ] as const;
  const current = choices.find((c) => c.id === (value?.kind || "image"))!;
  const Icon = current.icon;
  return (
    <>
      <button
        type="button"
        className="composer-option tool-trigger"
        aria-haspopup="dialog"
        aria-label={t("Choose a tool")}
        onClick={() => setOpen(true)}
      >
        <Icon size={16} />
        {t(current.name)}
        <ChevronDown size={13} />
      </button>
      {open && (
        <Modal title={t("Choose a tool")} wide onClose={() => setOpen(false)}>
          <div className="dialog-body tool-picker">
            <p>{t("What are you making?")}</p>
            <div className="tool-grid">
              {choices.map(({ id, name, description, icon: ToolIcon }) => (
                <button
                  type="button"
                  key={id}
                  className="tool-choice"
                  aria-pressed={current.id === id}
                  onClick={() => {
                    onChange(
                      id === "image"
                        ? null
                        : normalizeGameAsset({
                            ...defaultGameAsset,
                            kind: id,
                            action: id === "tileset" ? "variations" : "idle",
                          }),
                    );
                    setOpen(false);
                  }}
                >
                  <span className="tool-choice-icon">
                    <ToolIcon size={25} />
                    {current.id === id && <Check size={16} />}
                  </span>
                  <strong>{t(name)}</strong>
                  <span>{t(description)}</span>
                </button>
              ))}
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

export function GameControls({
  value,
  onChange,
}: {
  value: GameAsset;
  onChange: (v: GameAsset) => void;
}) {
  const character = value.kind === "spritesheet";
  const presets = character
    ? [
        {
          id: "idle",
          name: "Idle",
          icon: Wind,
          detail: "A quiet breathing loop",
        },
        {
          id: "walk",
          name: "Walk",
          icon: Footprints,
          detail: "Contact and passing poses",
        },
        {
          id: "attack",
          name: "Attack",
          icon: Swords,
          detail: "Wind-up, strike, recovery",
        },
        {
          id: "views",
          name: "Four views",
          icon: Rotate3D,
          detail: "Front, right, back, left",
        },
        {
          id: "custom",
          name: "Custom frames",
          icon: PencilLine,
          detail: "Write each pose yourself",
        },
      ]
    : [
        {
          id: "variations",
          name: "Material variations",
          icon: Grid2X2,
          detail: "One material, several patterns",
        },
        {
          id: "custom",
          name: "Custom tiles",
          icon: PencilLine,
          detail: "Describe each tile yourself",
        },
      ];
  const update = (patch: Partial<GameAsset>) =>
    onChange({ ...value, ...patch });
  return (
    <div className="game-setup">
      <div className="preset-grid">
        {presets.map(({ id, name, icon: Icon, detail }) => (
          <button
            type="button"
            key={id}
            aria-pressed={value.action === id}
            onClick={() => update({ action: id as GameAsset["action"] })}
          >
            <Icon size={21} />
            <span>
              <strong>{t(name)}</strong>
              <small>{t(detail)}</small>
            </span>
            {value.action === id && <Check size={16} />}
          </button>
        ))}
      </div>
      {value.action === "custom" ? (
        <label className="custom-frame-field">
          {t("One frame per line")}
          <textarea
            rows={5}
            value={(value.custom_frames || []).join("\n")}
            maxLength={6408}
            onChange={(e) =>
              update({ custom_frames: e.target.value.split("\n") })
            }
            placeholder={t(
              character
                ? "Standing ready\nDrawing the sword\nSword extended forward\nReturning to ready"
                : "Small cobblestones\nCracked cobblestones\nMossy cobblestones",
            )}
          />
          <small>
            {t(
              "Up to 8 frames. Your main prompt describes what stays consistent.",
            )}
          </small>
        </label>
      ) : (
        value.action !== "views" && (
          <div className="setup-row">
            <span>{t(character ? "Frames" : "Tiles")}</span>
            <div className="segmented">
              {[2, 4, 6, 8].map((n) => (
                <button
                  type="button"
                  key={n}
                  className={value.count === n ? "active" : ""}
                  aria-pressed={value.count === n}
                  onClick={() => update({ count: n })}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        )
      )}
      {character && value.action !== "views" && (
        <div className="setup-row">
          <span>{t("Facing")}</span>
          <div className="segmented">
            {(["front", "right", "back", "left"] as const).map((d) => (
              <button
                type="button"
                key={d}
                className={value.direction === d ? "active" : ""}
                aria-pressed={value.direction === d}
                onClick={() => update({ direction: d })}
              >
                {t(
                  {
                    front: "Front",
                    right: "Right",
                    back: "Back",
                    left: "Left",
                  }[d],
                )}
              </button>
            ))}
          </div>
        </div>
      )}
      {!character && (
        <label className="check-label">
          <input
            type="checkbox"
            checked={value.seamless !== false}
            onChange={(e) => update({ seamless: e.target.checked })}
          />
          {t("Match opposite edges for repeating textures")}
        </label>
      )}
      <p className="setup-note">
        {t(
          character
            ? "Each pose is generated separately, using the first frame as the character reference. Frames are aligned on a shared ground line. Preview motion and adjust alignment in the workshop."
            : "Each tile is generated separately. Preview repeats and paint a test map in the workshop. Different materials may still need transition tiles.",
        )}
      </p>
      <p className="setup-note">
        {t(
          "Use the single Pixel switch in the composer for pixel art. Export size and playback speed can be changed later.",
        )}
      </p>
    </div>
  );
}

function readWorkshop(asset: Asset, total: number) {
  if (asset.temporary || asset.personal) return {};
  try {
    const v = JSON.parse(
      localStorage.getItem("atelier.workshop." + asset.id) || "{}",
    );
    return {
      cell:
        Number.isInteger(v.cell) && v.cell >= 16 && v.cell <= 256
          ? v.cell
          : undefined,
      fps:
        Number.isInteger(v.fps) && v.fps >= 1 && v.fps <= 30
          ? v.fps
          : undefined,
      offsets:
        Array.isArray(v.offsets) &&
        v.offsets.length === total &&
        v.offsets.every(
          (p: unknown) =>
            Array.isArray(p) &&
            p.length === 2 &&
            p.every(
              (n) => Number.isInteger(n) && Math.abs(n) <= (v.cell || 64),
            ),
        )
          ? (v.offsets as number[][])
          : undefined,
      layout:
        Array.isArray(v.layout) &&
        v.layout.length === 144 &&
        v.layout.every(
          (n: unknown) =>
            typeof n === "number" &&
            Number.isInteger(n) &&
            n >= 0 &&
            n <= total,
        )
          ? (v.layout as number[])
          : undefined,
    };
  } catch {
    return {};
  }
}
export function GameWorkbench({
  asset,
  onClose,
  onUseFrame,
}: {
  asset: Asset;
  onClose: () => void;
  onUseFrame: (reference: Asset) => void;
}) {
  const tool = asset.metadata.game_asset as GameAsset;
  const character = tool.kind === "spritesheet";
  const total = tool.count || tool.columns * tool.rows;
  const [draft] = useState(() => readWorkshop(asset, total));
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(character && tool.action !== "views");
  const [fps, setFps] = useState(draft.fps || tool.fps);
  const [cell, setCell] = useState(draft.cell || tool.cell_size);
  const [offsets, setOffsets] = useState<number[][]>(
    draft.offsets || Array.from({ length: total }, () => [0, 0]),
  );
  const [onion, setOnion] = useState(false);
  const [tile, setTile] = useState(1);
  const [mapView, setMapView] = useState(false);
  const [layout, setLayout] = useState<number[]>(
    draft.layout || Array(144).fill(0),
  );
  const [past, setPast] = useState<number[][]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [src, setSrc] = useState("");
  const previewOptions = JSON.stringify({ cell_size: cell, offsets });
  useEffect(() => {
    const controller = new AbortController();
    let url = "";
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const r = await studioFetch(
          `/api/assets/${asset.id}/game-export?preview=true`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ options: JSON.parse(previewOptions) }),
            signal: controller.signal,
          },
        );
        if (!r.ok) throw new Error((await r.json()).error);
        const blob = await r.blob();
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
        setError("");
        setLoading(false);
      } catch (e) {
        if (!controller.signal.aborted) {
          setError((e as Error).message);
          setLoading(false);
        }
      }
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [asset.id, previewOptions]);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(
      () => setFrame((f) => (f + 1) % total),
      1000 / fps,
    );
    return () => clearInterval(timer);
  }, [playing, total, fps]);
  useEffect(() => {
    if (asset.temporary || asset.personal) return;
    try {
      localStorage.setItem(
        "atelier.workshop." + asset.id,
        JSON.stringify({ fps, cell, offsets, layout }),
      );
    } catch {
      /* Export still works without browser storage. */
    }
  }, [asset.id, asset.temporary, fps, cell, offsets, layout]);
  const style = (index: number) => ({
    backgroundImage: src ? `url("${src}")` : undefined,
    backgroundSize: `${tool.columns * 100}% ${tool.rows * 100}%`,
    backgroundPosition: `${tool.columns === 1 ? 0 : ((index % tool.columns) / (tool.columns - 1)) * 100}% ${tool.rows === 1 ? 0 : (Math.floor(index / tool.columns) / (tool.rows - 1)) * 100}%`,
  });
  const select = (index: number) => {
    setFrame((index + total) % total);
    setPlaying(false);
    setTile(index + 1);
  };
  const paint = (next: number[]) => {
    setPast((old) => [...old.slice(-19), layout]);
    setLayout(next);
  };
  const download = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await studioFetch(`/api/assets/${asset.id}/game-export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          layout: character ? null : layout,
          options: { cell_size: cell, fps, offsets },
        }),
      });
      if (!response.ok) throw new Error((await response.json()).error);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `atelier-${tool.action || tool.kind}-${asset.seed}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t(character ? "Animation workshop" : "Tile workshop")}
      wide
      onClose={onClose}
    >
      <div
        className={`dialog-body game-workbench${asset.metadata.pixelation || tool.pixel_art ? " is-pixel" : ""}`}
      >
        {tool.generation !== "individual" && (
          <p className="workshop-notice">
            {t(
              "This is an older grid-generated sheet. If cells do not line up, use Reuse settings to regenerate with individual frames.",
            )}
          </p>
        )}
        <div className="workshop-main">
          <div className="workshop-view">
            {character ? (
              <>
                <div
                  className="animation-stage"
                  aria-label={t("Animation preview")}
                  aria-busy={loading}
                >
                  {onion && !playing && (
                    <div
                      className="onion-frame"
                      style={style((frame + total - 1) % total)}
                    />
                  )}
                  <div className="current-frame" style={style(frame)} />
                  <div className="ground-guide" />
                </div>
                <div className="playback-bar">
                  <button
                    className="icon-btn"
                    aria-label={t("Previous frame")}
                    onClick={() => select(frame - 1)}
                  >
                    <ChevronLeft size={18} />
                  </button>
                  <button
                    className="secondary"
                    onClick={() => setPlaying(!playing)}
                  >
                    {playing ? <Pause size={16} /> : <Play size={16} />}
                    {t(playing ? "Pause" : "Play")}
                  </button>
                  <button
                    className="icon-btn"
                    aria-label={t("Next frame")}
                    onClick={() => select(frame + 1)}
                  >
                    <ChevronRight size={18} />
                  </button>
                  <span>{t("Frame {0} / {1}", frame + 1, total)}</span>
                </div>
              </>
            ) : (
              <>
                <div className="segmented workshop-tabs">
                  <button
                    className={!mapView ? "active" : ""}
                    onClick={() => setMapView(false)}
                  >
                    {t("Repeat preview")}
                  </button>
                  <button
                    className={mapView ? "active" : ""}
                    onClick={() => setMapView(true)}
                  >
                    {t("Test map")}
                  </button>
                </div>
                {mapView ? (
                  <div
                    className="tilemap-grid"
                    aria-label={t("Paint a 12 × 12 map")}
                  >
                    {layout.map((id, i) => (
                      <button
                        key={i}
                        aria-label={t("Map cell {0}", i + 1)}
                        style={id ? style(id - 1) : {}}
                        onPointerEnter={(e) => {
                          if (e.buttons === 1)
                            paint(layout.map((v, n) => (n === i ? tile : v)));
                        }}
                        onClick={() =>
                          paint(layout.map((v, n) => (n === i ? tile : v)))
                        }
                      />
                    ))}
                  </div>
                ) : (
                  <div className="repeat-preview">
                    {Array.from({ length: 9 }, (_, i) => (
                      <div key={i} style={style(Math.max(0, tile - 1))} />
                    ))}
                  </div>
                )}
                {mapView && (
                  <div className="game-map-actions">
                    <button
                      className="secondary"
                      onClick={() => paint(Array(144).fill(tile))}
                    >
                      {t("Fill")}
                    </button>
                    <button
                      className="secondary"
                      aria-pressed={tile === 0}
                      onClick={() => setTile(0)}
                    >
                      {t("Eraser")}
                    </button>
                    <button
                      className="icon-btn"
                      aria-label={t("Undo")}
                      disabled={!past.length}
                      onClick={() => {
                        setLayout(past[past.length - 1]);
                        setPast(past.slice(0, -1));
                      }}
                    >
                      <Undo2 size={17} />
                    </button>
                  </div>
                )}
              </>
            )}
            <div
              className="frame-strip"
              aria-label={t(character ? "Frames" : "Tiles")}
            >
              {Array.from({ length: total }, (_, i) => (
                <button
                  key={i}
                  aria-label={t("Cell {0}", i + 1)}
                  aria-pressed={character ? frame === i : tile === i + 1}
                  onClick={() => select(i)}
                >
                  <span style={style(i)} />
                  <small>{i + 1}</small>
                </button>
              ))}
            </div>
          </div>
          <div className="workshop-settings">
            <h3>{t("Export & playback")}</h3>
            <label>
              {t("Cell size")}
              <select
                value={cell}
                onChange={(e) => {
                  const next = Number(e.target.value);
                  setOffsets((old) =>
                    old.map((p) => p.map((n) => Math.round((n * next) / cell))),
                  );
                  setCell(next);
                }}
              >
                {[...new Set([16, 32, 48, 64, 96, 128, 256, cell])]
                  .sort((a, b) => a - b)
                  .map((n) => (
                    <option key={n} value={n}>
                      {n} × {n}
                    </option>
                  ))}
              </select>
            </label>
            {character && (
              <>
                <label>
                  {t("Animation FPS")}
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={fps}
                    onChange={(e) =>
                      setFps(
                        Math.max(1, Math.min(30, Number(e.target.value) || 1)),
                      )
                    }
                  />
                </label>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={onion}
                    onChange={(e) => {
                      setOnion(e.target.checked);
                      setPlaying(false);
                    }}
                  />
                  {t("Show previous frame")}
                </label>
                <details>
                  <summary>{t("Adjust frame alignment")}</summary>
                  <p>
                    {t(
                      "Select a frame below the preview, then move it within its cell. Anything beyond the cell is clipped.",
                    )}
                  </p>
                  <div className="frame-offsets">
                    {["X", "Y"].map((axis, i) => (
                      <label key={axis}>
                        {axis}
                        <input
                          aria-label={t("Frame offset {0}", axis)}
                          type="number"
                          min={-cell}
                          max={cell}
                          value={offsets[frame][i]}
                          onFocus={() => setPlaying(false)}
                          onChange={(e) =>
                            setOffsets((old) =>
                              old.map((p, n) =>
                                n === frame
                                  ? p.map((v, a) =>
                                      a === i
                                        ? Math.max(
                                            -cell,
                                            Math.min(
                                              cell,
                                              Number(e.target.value) || 0,
                                            ),
                                          )
                                        : v,
                                    )
                                  : p,
                              ),
                            )
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <button
                    className="quiet"
                    onClick={() =>
                      setOffsets((old) =>
                        old.map((p, i) => (i === frame ? [0, 0] : p)),
                      )
                    }
                  >
                    {t("Reset this frame")}
                  </button>
                </details>
              </>
            )}
            <p>
              {t(
                "The pack includes an atlas, individual PNGs and frame metadata. Tile maps use Tiled JSON. Your original image stays unchanged.",
              )}
            </p>
            <p>
              {t(
                asset.temporary
                  ? "Temporary session: download the pack before leaving."
                  : "Workshop settings are saved in this browser.",
              )}
            </p>
          </div>
        </div>
        {error && (
          <p className="error" role="alert">
            {t(error)}
          </p>
        )}
        <div className="dialog-actions">
          {character && (
            <button
              className="secondary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const response = await studioFetch(
                    `/api/assets/${asset.id}/game-frame`,
                    {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ index: frame }),
                    },
                  );
                  if (!response.ok)
                    throw new Error((await response.json()).error);
                  onUseFrame(await response.json());
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t("Use selected frame as reference")}
            </button>
          )}
          <button
            className="primary"
            disabled={busy || loading || !src}
            onClick={() => void download()}
          >
            <Download size={17} />
            {t(busy ? "Exporting…" : "Download game asset pack")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
