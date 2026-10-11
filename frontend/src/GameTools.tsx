import { t } from "./i18n";
import { useEffect, useState } from "react";
import { Download, Pause, Play } from "lucide-react";
import { Modal } from "./ui";
import type { Asset, GameAsset } from "./types";

export const defaultGameAsset: GameAsset = {
  kind: "spritesheet",
  columns: 4,
  rows: 2,
  cell_size: 32,
  fps: 8,
  pixel_art: true,
  palette: 32,
};
export function GameToolSelect({
  value,
  onChange,
}: {
  value: GameAsset | null;
  onChange: (v: GameAsset | null) => void;
}) {
  return (
    <label className="composer-tool-select">
      <span className="sr-only">{t("Image tool")}</span>
      <select
        aria-label={t("Image tool")}
        value={value?.kind || "image"}
        onChange={(e) =>
          onChange(
            e.target.value === "image"
              ? null
              : {
                  ...(value || defaultGameAsset),
                  kind: e.target.value as GameAsset["kind"],
                },
          )
        }
      >
        <option value="image"> {t("Default image")} </option>
        <optgroup label={t("Game development")}>
          <option value="tileset"> {t("Tileset & tile map")} </option>
          <option value="spritesheet"> {t("Character sprite sheet")} </option>
        </optgroup>
      </select>
    </label>
  );
}

export function GameControls({
  value,
  onChange,
}: {
  value: GameAsset;
  onChange: (value: GameAsset) => void;
}) {
  return (
    <div className="game-controls">
      {(["columns", "rows", "cell_size", "palette", "fps"] as const).map(
        (name) => (
          <label key={name}>
            {" "}
            {t(
              {
                columns: "Columns",
                rows: "Rows",
                cell_size: "Export cell (px)",
                palette: "Palette colors",
                fps: "Animation FPS",
              }[name],
            )}{" "}
            <input
              type="number"
              min={name === "cell_size" ? 16 : name === "palette" ? 2 : 1}
              max={
                name === "columns" || name === "rows"
                  ? 8
                  : name === "fps"
                    ? 30
                    : 256
              }
              value={value[name]}
              onChange={(e) =>
                onChange({ ...value, [name]: Number(e.target.value) })
              }
            />
          </label>
        ),
      )}
      <label className="check-label">
        <input
          type="checkbox"
          checked={value.pixel_art}
          onChange={(e) => onChange({ ...value, pixel_art: e.target.checked })}
        />{" "}
        {t("Pixel art")}{" "}
      </label>
      <p>
        {" "}
        {t(
          "Describe the character and animation, or the terrain and tile types. A grid prompt is added automatically. Export crops equal cells; check poses and seams before using them in a game.",
        )}{" "}
      </p>
      <p>{t("Canvas follows the grid so exported cells stay square.")}</p>
    </div>
  );
}

export function GameWorkbench({
  asset,
  onClose,
}: {
  asset: Asset;
  onClose: () => void;
}) {
  const tool = asset.metadata.game_asset as GameAsset;
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(tool.kind === "spritesheet");
  const [tile, setTile] = useState(1);
  const [layout, setLayout] = useState<number[]>(Array(144).fill(0));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const src = `/api/assets/${asset.id}/game-export?preview=true`;
  const total = tool.columns * tool.rows;
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(
      () => setFrame((f) => (f + 1) % total),
      1000 / tool.fps,
    );
    return () => clearInterval(timer);
  }, [playing, total, tool.fps]);
  const style = (index: number) => ({
    backgroundImage: `url("${src}")`,
    backgroundSize: `${tool.columns * 100}% ${tool.rows * 100}%`,
    backgroundPosition: `${tool.columns === 1 ? 0 : ((index % tool.columns) / (tool.columns - 1)) * 100}% ${tool.rows === 1 ? 0 : (Math.floor(index / tool.columns) / (tool.rows - 1)) * 100}%`,
  });
  const download = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/assets/${asset.id}/game-export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          layout: tool.kind === "tileset" ? layout : null,
        }),
      });
      if (!response.ok) throw new Error((await response.json()).error);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "atelier-game-assets.zip";
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
      title={t(
        tool.kind === "tileset" ? "Tile map workshop" : "Sprite sheet workshop",
      )}
      wide
      onClose={onClose}
    >
      <div className="dialog-body game-workbench">
        <p>
          {" "}
          {t(
            "Original generation is preserved. Export includes atlas PNG, separate cells and animation metadata. Tile maps use Tiled JSON.",
          )}{" "}
        </p>
        <div className="game-workbench-grid">
          <div>
            <h3> {t("Choose a cell")} </h3>
            <div
              className="tile-palette"
              style={{ gridTemplateColumns: `repeat(${tool.columns}, 1fr)` }}
            >
              {Array.from({ length: total }, (_, i) => (
                <button
                  key={i}
                  aria-label={t(`Cell ${i + 1}`)}
                  aria-pressed={tile === i + 1}
                  style={style(i)}
                  onClick={() => {
                    setTile(i + 1);
                    setFrame(i);
                    setPlaying(false);
                  }}
                />
              ))}
            </div>
            <p>
              {tool.cell_size} × {tool.cell_size} {t("px ·")} {total}{" "}
              {t("cells")}{" "}
            </p>
          </div>
          <div>
            {tool.kind === "spritesheet" ? (
              <>
                <h3> {t("Animation preview")} </h3>
                <div className="sprite-preview" style={style(frame)} />
                <button
                  className="secondary"
                  onClick={() => setPlaying(!playing)}
                >
                  {playing ? <Pause size={16} /> : <Play size={16} />}{" "}
                  {t(playing ? "Pause" : "Play")}{" "}
                </button>
                <p>
                  {frame + 1} / {total} · {tool.fps} {t("FPS")}{" "}
                </p>
              </>
            ) : (
              <>
                <h3> {t("Paint a 12 × 12 map")} </h3>
                <p>
                  {t(
                    "Map edits stay here until you download. Closing this workshop resets the map.",
                  )}
                </p>
                <div className="tilemap-grid">
                  {layout.map((id, i) => (
                    <button
                      key={i}
                      aria-label={t(`Map cell ${i + 1}`)}
                      style={id ? style(id - 1) : {}}
                      onClick={() =>
                        setLayout((old) =>
                          old.map((v, n) => (n === i ? tile : v)),
                        )
                      }
                    />
                  ))}
                </div>
                <div className="game-map-actions">
                  <button
                    className="secondary"
                    onClick={() => setLayout(Array(144).fill(tile))}
                  >
                    {" "}
                    {t("Fill with selected tile")}{" "}
                  </button>
                  <button className="quiet" onClick={() => setTile(0)}>
                    {" "}
                    {t("Eraser")}{" "}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
        {error && (
          <p className="error" role="alert">
            {" "}
            {t(error)}{" "}
          </p>
        )}
        <div className="dialog-actions">
          <button
            className="primary"
            disabled={busy}
            onClick={() => void download()}
          >
            <Download size={17} />{" "}
            {t(busy ? "Exporting…" : "Download game asset pack")}{" "}
          </button>
        </div>
      </div>
    </Modal>
  );
}
