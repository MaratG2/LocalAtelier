import { t } from "./i18n";
import { useRef, useState } from "react";
import { Maximize, Pause, Play, Volume2, VolumeX } from "lucide-react";
import type { Asset } from "./types";

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
export default function VideoPlayer({ asset }: { asset: Asset }) {
  const video = useRef<HTMLVideoElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(
    Number(asset.metadata.duration) || 0,
  );
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [error, setError] = useState("");
  const toggle = () => {
    const element = video.current;
    if (!element) return;
    if (element.paused)
      void element
        .play()
        .catch(() =>
          setError(
            "Playback could not start. Download the MP4 to open it in your video player.",
          ),
        );
    else element.pause();
  };
  const seek = (value: number) => {
    if (video.current) video.current.currentTime = value;
    setTime(value);
  };
  return (
    <div className="clip-player" ref={shell}>
      <div className="clip-screen">
        <video
          ref={video}
          src={asset.url}
          poster={asset.thumbnail_url}
          playsInline
          preload="metadata"
          muted={muted}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onError={() =>
            setError(
              "This browser could not read the clip. Download the MP4 to play it locally.",
            )
          }
          onClick={toggle}
          aria-label={asset.name}
        />
        {!playing && (
          <button
            className="clip-play-overlay"
            aria-label={t("Play video")}
            onClick={toggle}
          >
            <Play size={25} fill="currentColor" />
          </button>
        )}
        <span className="clip-version">
          {" "}
          {t(asset.metadata.preview ? "Preview" : "Finished clip")}{" "}
        </span>
      </div>
      <div className="clip-controls">
        <button
          className="icon-btn"
          aria-label={t(playing ? "Pause video" : "Play video")}
          onClick={toggle}
        >
          {playing ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <span className="clip-time">
          {" "}
          {t(clock(time))} / {t(clock(duration))}{" "}
        </span>
        <input
          aria-label={t("Seek video")}
          type="range"
          min="0"
          max={duration || 1}
          step="0.01"
          value={time}
          onChange={(e) => seek(Number(e.target.value))}
        />
        <button
          className="icon-btn"
          aria-label={t(muted ? "Unmute audio" : "Mute audio")}
          onClick={() => setMuted(!muted)}
        >
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <input
          className="clip-volume"
          aria-label={t("Audio volume")}
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={volume}
          onChange={(e) => {
            const value = Number(e.target.value);
            setVolume(value);
            setMuted(value === 0);
            if (video.current) video.current.volume = value;
          }}
        />
        <button
          className="icon-btn"
          aria-label={t("Full screen")}
          onClick={() => {
            const action = document.fullscreenElement
              ? document.exitFullscreen()
              : shell.current?.requestFullscreen();
            void action?.catch(() =>
              setError("Full screen is unavailable in this browser."),
            );
          }}
        >
          <Maximize size={17} />
        </button>
      </div>
      <button
        className="clip-filmstrip"
        aria-label={t("Seek to a frame")}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          seek(
            Math.max(
              0,
              Math.min(
                duration,
                ((e.clientX - rect.left) / rect.width) * duration,
              ),
            ),
          );
        }}
      >
        <img
          src={`/api/videos/${asset.id}/filmstrip`}
          alt={t("Five frames from this clip")}
        />
        <i style={{ left: `${(time / Math.max(duration, 1)) * 100}%` }} />
      </button>
      {error && (
        <p className="error-text" role="alert">
          {" "}
          {t(error)}{" "}
        </p>
      )}
    </div>
  );
}
