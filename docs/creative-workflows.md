# Creative workflows

## English and Russian

The language selector is at the bottom of the sidebar (inside the navigation menu on narrow screens). The first visit follows the browser language; subsequent visits remember the selection. Switching language does not reset prompts or generation settings. User prompts, project names, model identifiers and raw third-party diagnostic logs keep their original content. The interface, help text, accessibility labels, model descriptions, application validation and known generation stages have Russian translations. Dates, file sizes and plural forms follow the selected locale.

`frontend/src/i18n.tsx` and `ru.json` own localization. `npm run check:locales` checks visible static text, dictionary coverage, interpolation, language switching and Russian plural forms. Add new UI copy through `t()` rather than changing the DOM after rendering.

## Incognito / temporary sessions

Use the Incognito switch above the workspace **before** writing a private prompt or uploading private references. Confirming starts a clean temporary workspace for images, 3D and video. The normal draft is preserved and returns when temporary mode ends. Temporary prompts and settings are not written to browser localStorage. Language preference may still be saved.

Temporary job and asset records use an in-memory SQLite database, separate from `data/atelier.sqlite3`. Native GPU pipelines require files: inputs, outputs, metadata, logs, previews and content-bearing scratch files are written under `data/temporary/<session-id>/`. This is not a RAM-only or secure-erasure feature. OS swap, crash dumps, backups and files deliberately downloaded by the user are outside this application cleanup guarantee. Avoid backing up `data/temporary`.

Results trigger a **download now** reminder. Downloading explicitly keeps the file on the user's disk; dismissing the reminder does not save it. There is no automatic promotion into project history. Original images, GLB objects and MP4 clips remain available in the temporary library while the session is open. Game asset packs can be downloaded through their workshop.

Ending the session, closing/reloading its tab, or losing connection for 15 minutes requests disposal. Queued work is cancelled. Running image inference finishes its current image before cleanup; video and native mesh inference cancel through their worker adapters. Cleanup waits for owned worker processes to release file handles. A visible error reports failed cleanup, and the reaper retries. Marked orphan session directories are retried at the next studio startup. Browser close notifications are best effort; the inactivity timeout covers abrupt browser termination. In-memory job history disappears on server exit.

The session is scoped to this browser's cookie, so tabs of the same localhost origin share it. Ending or reloading one temporary tab ends that session for the others. Existing saved assets may be read as references but cannot be modified in temporary mode. Project edits, model operations and settings writes require leaving incognito. Active jobs in every session still protect the shared GPU, models and referenced assets.

Qwen content directories (input/output/temp/user) and worker logs live under the active session root. HiDream scratch and TRELLIS work directories use the same root. H3 disables reusable prompt conditioning with `--no-tuning` and uses a session-specific FreeVideo home and temporary directory; model weights and non-content kernel caches remain shared. The app returns `Cache-Control: no-store` for API responses and media.

The bundled `run.py` server omits query strings from access logs so library searches do not retain private text. A custom proxy or alternative server must provide its own equivalent log policy. Internal image-to-3D and image-to-video actions keep the current temporary session alive; leaving or reloading the application disposes it.

## Project art direction

New project / Edit project contains a style prompt and optional reference image. A project prompt takes precedence over the global image style in Settings. Empty prompts can inherit the global style; disable inheritance for a project that needs no default style.

Upload a reference at creation, generate one with Qwen after creating the project, or choose **Use as project style reference** from image details. Generated references remain ordinary project images. Save project changes to make a generated reference the default.

Open **Style** beside the image tool selector to access independent **Project style** and **Style reference** switches and **Edit style**. The collapsed button shows automatic style, reference style, or style off. Style text is appended to the user's prompt when the job is queued. The reference is inserted into reference mode automatically, counts toward the model's reference limit, and is recorded in metadata. Choosing Create or Edit explicitly disables the automatic reference for that draft. Edit uses only its selected image. Removing the project reference does not delete its original image. Changes after submission do not alter queued jobs.

Style controls apply to Images. They do not silently alter TRELLIS or H3 prompts. Reuse settings preserves the original user prompt without appending style or grid instructions a second time. Style consistency is guidance, not an identity lock or a guarantee of identical poses and colors.

## Pixel finishing

Enable **Pixel** beside **Transparent background** in Images to process the generated result on the CPU. It works with either image model, Create / Edit / References, batches and game tools. The switch is off by default. Enabling it opens Advanced; collapsing Advanced keeps the switch and settings active.

Start the studio through **Start.cmd** to enable managed startup and automatic backend reload. The launcher replaces a verified idle older instance when needed, then applies future backend updates after active work and incognito sessions finish. The interface checks the backend's advertised `image-pixelation` capability before queueing; an older backend shows a restart message instead of receiving unsupported settings.

Advanced → **Pixel finish** sets the output block size (2, 4, 8, 16 or 32 px) and maximum palette size (presets of 8, 16, 32, 64, 128 or 256 colors). Defaults are 8 px and 32 colors, giving a 128×128 logical grid for a 1024×1024 output. The API accepts any integer palette limit from 2 through 256; Reuse settings preserves custom limits and adds them to the selector.

Pixel finishing separates two color groups within each cell instead of averaging across an outline. It normally keeps the dominant group, but preserves smaller connected features that strongly contrast with the surrounding cells, including dark outlines, light highlights and colored accents. The stricter detail rule lets broad boundaries such as cast shadows follow cell coverage, reducing extra teeth and notches. Low-contrast shading retains its average instead of snapping to one half of its colors. Isolated specks cannot expand into whole feature blocks; incoherent noise is averaged. Colors are reduced without dithering and matched to the closest palette color, then enlarged with nearest-neighbor sampling. This avoids soft mixed edge colors and bright background specks caused by coarse palette matching. Processing is deterministic and runs in bounded strips on the CPU.

Output dimensions stay unchanged; any partial edge cells are cropped. Bigger blocks simplify more detail; choose 4 px or more colors to retain finer features. A preserved thin line can become one full block wide, and curves still have steps at the chosen grid size. Pixel finishing enforces a grid and palette, but cannot restore missing details or fix incorrect shapes, poses or tile seams. New PNGs record algorithm `coverage-cluster-nearest-v3`; existing outputs are unchanged, and Reuse settings generates with the current algorithm.

Native transparency is retained with a hard silhouette: average alpha below 128 becomes transparent, and alpha at or above 128 becomes opaque. Semi-transparent materials therefore become opaque or transparent. Pixel finishing does not remove an opaque background; request native transparency separately when needed.

The finished PNG is the generated asset; a separate unprocessed copy is not added to the library. Uploaded references remain unchanged. Thumbnails use nearest-neighbor sampling. PNG metadata, the JSON sidecar and Reuse settings retain pixel settings; the regular project draft remembers them as well. Incognito keeps the same temporary lifecycle and does not write these draft settings to browser storage. Game workshop export has its own cell size and palette controls and can further reduce an already pixel-finished image.

## Game development tools

Images → **Image tool** offers Default image, Character sprite sheet, and Tileset & tile map. Select a 1–8 column/row grid, 16–256 px export cell, frame rate, pixel-art mode and palette size. Grid aspect ratios are limited to 4:1 so the model's supported 512–2048 canvas can use square source cells. The requested resolution is adjusted to a compatible grid and multiples of 64. Square source cells avoid stretching during export.

The tool selector sits beside Create / Edit / References. Choosing a game tool opens its settings; the compact grid button reopens them later. Close the panel with its close button or Escape to return to the compact composer; keyboard focus returns to the settings button. Collapsing settings preserves their values, and choosing Default image removes the game grid instructions.

The generation request adds grid, camera, lighting and consistency guidance. Describe the actual character, action, terrain or transitions in the prompt. Project art direction and reference overrides continue to apply. Qwen's existing transparent-background switch can request native alpha; exports preserve the source alpha rather than guessing a background color.

Open a generated image's details and choose **Open game asset workshop**. Sprite sheets have cell selection and an animation preview in row-major order. Tilesets have a 12×12 paintable map, selected-tile fill and eraser. Download the map before closing the workshop; map edits are currently held only in that workshop session.

The ZIP contains `atlas.png`, individual `frames/*.png`, and Aseprite-style `atlas.json` with frame rectangles, durations and a default animation tag. Tilesets add `tileset.tsj`; the painted map adds `map.tmj`, both Tiled JSON. PNG cells are cropped from the equal source grid and resized to the requested cell dimensions. Pixel mode uses nearest-neighbor sampling and a shared limited palette without dithering; non-pixel mode uses Lanczos. The original generation is retained unchanged.

Review generated cell boundaries, animation poses, alignment and tile seams. Grid prompting and deterministic export do not guarantee perfect animation continuity or seamless transitions, and this release has no skeleton animation solver or automatic terrain adjacency system.
