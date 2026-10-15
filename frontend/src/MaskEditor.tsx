import { useEffect, useRef, useState, type PointerEvent } from "react";
import {
  Brush,
  Eraser,
  Undo2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
  LoaderCircle,
} from "lucide-react";
import { api } from "./api";
import { t } from "./i18n";
import { Modal } from "./ui";
import type { Asset } from "./types";
import "./mask-editor.css";

export function MaskEditor({
  source,
  initialMask,
  initialFeather,
  strength,
  onClose,
  onApply,
}: {
  source: Asset;
  initialMask: Asset | null;
  initialFeather: number;
  strength?: { value: number; min: number; max: number };
  onClose: () => void;
  onApply: (mask: Asset, feather: number, strength?: number) => void;
}) {
  const overlay = useRef<HTMLCanvasElement>(null);
  const paint = useRef<HTMLCanvasElement | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const undo = useRef<ImageData[]>([]);
  const pointer = useRef<{ id: number; x: number; y: number } | null>(null);
  const keyboard = useRef({ x: 0, y: 0 });
  const [brush, setBrush] = useState(56);
  const [erase, setErase] = useState(false);
  const [feather, setFeather] = useState(initialFeather);
  const [amount, setAmount] = useState(strength?.value ?? 0.45);
  const [zoom, setZoom] = useState(1);
  const [availableWidth, setAvailableWidth] = useState(600);
  const [ready, setReady] = useState(false);
  const [sourceReady, setSourceReady] = useState(false);
  const [hasPaint, setHasPaint] = useState(false);
  const [undoCount, setUndoCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const scale = Math.min(1, 1024 / Math.max(source.width, source.height));
  const width = Math.max(1, Math.round(source.width * scale));
  const height = Math.max(1, Math.round(source.height * scale));
  const drawOverlay = () => {
    const canvas = overlay.current,
      mask = paint.current;
    if (!canvas || !mask) return;
    const context = canvas.getContext("2d")!;
    context.clearRect(0, 0, width, height);
    context.globalCompositeOperation = "source-over";
    context.drawImage(mask, 0, 0);
    context.globalCompositeOperation = "source-in";
    context.fillStyle = "rgba(210, 77, 94, 0.55)";
    context.fillRect(0, 0, width, height);
    context.globalCompositeOperation = "source-over";
  };
  const updateSelection = () => {
    const pixels = paint
      .current!.getContext("2d")!
      .getImageData(0, 0, width, height).data;
    let selected = false;
    for (let i = 3; i < pixels.length; i += 4)
      if (pixels[i]) {
        selected = true;
        break;
      }
    setHasPaint(selected);
    drawOverlay();
  };
  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    paint.current = canvas;
    keyboard.current = { x: width / 2, y: height / 2 };
    let disposed = false;
    if (initialMask) {
      const image = new Image();
      image.onload = () => {
        if (disposed) return;
        const context = canvas.getContext("2d")!;
        context.drawImage(image, 0, 0, width, height);
        const pixels = context.getImageData(0, 0, width, height);
        for (let i = 0; i < pixels.data.length; i += 4) {
          pixels.data[i + 3] = pixels.data[i];
          pixels.data[i] = pixels.data[i + 1] = pixels.data[i + 2] = 255;
        }
        context.putImageData(pixels, 0, 0);
        updateSelection();
        setReady(true);
      };
      image.onerror = () => {
        if (!disposed)
          setError(
            "The mask could not be loaded. Close the editor and try again.",
          );
      };
      image.src = initialMask.url;
    } else {
      setReady(true);
      drawOverlay();
    }
    const observer = new ResizeObserver(([entry]) =>
      setAvailableWidth(entry.contentRect.width),
    );
    if (viewport.current) observer.observe(viewport.current);
    return () => {
      disposed = true;
      observer.disconnect();
      undo.current = [];
      paint.current = null;
    };
  }, []);
  const checkpoint = () => {
    undo.current.push(
      paint.current!.getContext("2d")!.getImageData(0, 0, width, height),
    );
    if (undo.current.length > 12) undo.current.shift();
    setUndoCount(undo.current.length);
  };
  const stroke = (x: number, y: number, from = { x, y }, erasing = erase) => {
    const context = paint.current!.getContext("2d")!;
    context.globalCompositeOperation = erasing
      ? "destination-out"
      : "source-over";
    context.strokeStyle = context.fillStyle = "white";
    context.lineCap = context.lineJoin = "round";
    context.lineWidth = brush;
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(x, y);
    context.stroke();
    context.beginPath();
    context.arc(x, y, brush / 2, 0, Math.PI * 2);
    context.fill();
    drawOverlay();
  };
  const location = (event: PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) * width) / rect.width,
      y: ((event.clientY - rect.top) * height) / rect.height,
    };
  };
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const output = document.createElement("canvas");
      output.width = source.width;
      output.height = source.height;
      const context = output.getContext("2d")!;
      context.fillStyle = "black";
      context.fillRect(0, 0, output.width, output.height);
      context.drawImage(paint.current!, 0, 0, output.width, output.height);
      const blob = await new Promise<Blob>((resolve, reject) =>
        output.toBlob(
          (value) =>
            value
              ? resolve(value)
              : reject(new Error("The mask could not be saved.")),
          "image/png",
        ),
      );
      const body = new FormData();
      body.set("source_id", source.id);
      body.set("mask", blob, "edit-mask.png");
      const mask = await api<Asset>("/edit-masks", { method: "POST", body });
      onApply(mask, feather, strength ? amount : undefined);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  const displayWidth =
    Math.max(
      1,
      Math.min(
        availableWidth,
        (Math.min(window.innerHeight * 0.48, 520) * source.width) /
          source.height,
      ),
    ) * zoom;
  return (
    <Modal
      title={t("Edit selected area")}
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="mask-editor">
        <p id="mask-instructions">
          {t(
            "Paint over what you want to change. Everything outside the selection stays unchanged.",
          )}
        </p>
        <div className="mask-toolbar">
          <div
            className="mask-brush-tools"
            role="group"
            aria-label={t("Mask tools")}
          >
            <button
              type="button"
              className={erase ? "secondary" : "primary"}
              aria-pressed={!erase}
              onClick={() => setErase(false)}
            >
              <Brush size={17} />
              {t("Brush")}
            </button>
            <button
              type="button"
              className={erase ? "primary" : "secondary"}
              aria-pressed={erase}
              onClick={() => setErase(true)}
            >
              <Eraser size={17} />
              {t("Eraser")}
            </button>
          </div>
          <button
            type="button"
            className="icon-btn"
            title={t("Undo stroke")}
            aria-label={t("Undo stroke")}
            disabled={!undoCount || busy}
            onClick={() => {
              const previous = undo.current.pop();
              if (previous)
                paint.current!.getContext("2d")!.putImageData(previous, 0, 0);
              setUndoCount(undo.current.length);
              updateSelection();
            }}
          >
            <Undo2 size={18} />
          </button>
          <button
            type="button"
            className="icon-btn"
            title={t("Clear selection")}
            aria-label={t("Clear selection")}
            disabled={!hasPaint || busy}
            onClick={() => {
              checkpoint();
              paint.current!.getContext("2d")!.clearRect(0, 0, width, height);
              updateSelection();
            }}
          >
            <RotateCcw size={18} />
          </button>
          <label className="mask-brush-size">
            {t("Brush size")}
            <input
              type="range"
              min="4"
              max="160"
              value={brush}
              onChange={(e) => setBrush(+e.target.value)}
            />
          </label>
          <div className="mask-zoom-tools">
            <button
              type="button"
              className="icon-btn"
              aria-label={t("Zoom out")}
              disabled={zoom <= 1}
              onClick={() => setZoom(Math.max(1, zoom - 0.5))}
            >
              <ZoomOut size={18} />
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              className="icon-btn"
              aria-label={t("Zoom in")}
              disabled={zoom >= 3}
              onClick={() => setZoom(Math.min(3, zoom + 0.5))}
            >
              <ZoomIn size={18} />
            </button>
          </div>
        </div>
        <div className="mask-viewport" ref={viewport}>
          <div
            className="mask-stage"
            style={{
              width: displayWidth,
              aspectRatio: `${source.width} / ${source.height}`,
            }}
          >
            <img
              src={source.url}
              alt={t("Image to edit")}
              draggable={false}
              onLoad={() => setSourceReady(true)}
              onError={() => setError("The source image could not be loaded.")}
            />
            <canvas
              ref={overlay}
              width={width}
              height={height}
              tabIndex={0}
              aria-label={t("Paint edit mask")}
              aria-describedby="mask-instructions mask-keyboard"
              onFocus={() => setCursor(keyboard.current)}
              onPointerLeave={() => {
                if (!pointer.current) setCursor(null);
              }}
              onPointerDown={(event) => {
                if (
                  !ready ||
                  !sourceReady ||
                  busy ||
                  pointer.current ||
                  event.button !== 0
                )
                  return;
                event.preventDefault();
                checkpoint();
                event.currentTarget.setPointerCapture(event.pointerId);
                const point = location(event);
                pointer.current = { id: event.pointerId, ...point };
                keyboard.current = point;
                setCursor(point);
                stroke(point.x, point.y, point, erase || event.shiftKey);
              }}
              onPointerMove={(event) => {
                setCursor(location(event));
                if (!pointer.current || pointer.current.id !== event.pointerId)
                  return;
                const point = location(event);
                stroke(
                  point.x,
                  point.y,
                  pointer.current,
                  erase || event.shiftKey,
                );
                pointer.current = { id: event.pointerId, ...point };
                keyboard.current = point;
              }}
              onPointerUp={() => {
                pointer.current = null;
                updateSelection();
              }}
              onPointerCancel={() => {
                pointer.current = null;
                updateSelection();
              }}
              onKeyDown={(event) => {
                if (!ready || busy) return;
                if (event.key === " ") {
                  event.preventDefault();
                  checkpoint();
                  stroke(keyboard.current.x, keyboard.current.y);
                  updateSelection();
                }
                const directions: Record<string, number[]> = {
                  ArrowLeft: [-1, 0],
                  ArrowRight: [1, 0],
                  ArrowUp: [0, -1],
                  ArrowDown: [0, 1],
                };
                const direction = directions[event.key];
                if (direction) {
                  event.preventDefault();
                  const step = event.shiftKey ? 1 : brush / 2;
                  keyboard.current = {
                    x: Math.max(
                      0,
                      Math.min(width, keyboard.current.x + direction[0] * step),
                    ),
                    y: Math.max(
                      0,
                      Math.min(
                        height,
                        keyboard.current.y + direction[1] * step,
                      ),
                    ),
                  };
                  setCursor(keyboard.current);
                }
              }}
            />
            {cursor && (
              <i
                className="mask-cursor"
                aria-hidden="true"
                style={{
                  left: `${(cursor.x / width) * 100}%`,
                  top: `${(cursor.y / height) * 100}%`,
                  width: `${(brush / width) * 100}%`,
                  height: `${(brush / height) * 100}%`,
                }}
              />
            )}
          </div>
        </div>
        <div className="mask-adjustments">
          <label>
            {t("Edge softness")}
            <input
              type="range"
              min="0"
              max="32"
              value={feather}
              onChange={(e) => setFeather(+e.target.value)}
            />
            <output>{feather}</output>
          </label>
          {strength && (
            <label>
              {t("Edit strength")}
              <input
                type="range"
                min={strength.min}
                max={strength.max}
                step="0.05"
                value={amount}
                onChange={(e) => setAmount(+e.target.value)}
              />
              <output>{Math.round(amount * 100)}%</output>
            </label>
          )}
        </div>
        <p className="muted-text">
          {t(
            "Soft edges and boundary color matching help the edit blend into its surroundings. Paint slightly beyond the object you want to replace.",
          )}
        </p>
        <details className="mask-keyboard">
          <summary>{t("Keyboard controls")}</summary>
          <p id="mask-keyboard">
            {t(
              "Focus the canvas. Arrow keys move the brush; Space paints. Hold Shift with an arrow for fine movement.",
            )}
          </p>
        </details>
        {error && (
          <p className="error-banner" role="alert">
            {t(error)}
          </p>
        )}
        <div className="dialog-actions">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            {t("Cancel")}
          </button>
          <button
            type="button"
            className="primary"
            disabled={!ready || !sourceReady || !hasPaint || busy}
            onClick={() => void save()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <Brush size={17} />
            )}{" "}
            {t(busy ? "Saving selection…" : "Use selection")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
