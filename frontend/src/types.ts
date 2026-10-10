export interface Project {
  id: string;
  name: string;
  description: string;
  favorite: number;
  archived: number;
  created: number;
  updated: number;
  asset_count?: number;
  cover_id?: string;
}
export interface Operation {
  id: string;
  action: string;
  status: string;
  phase: string;
  progress: number | null;
  logs: string[];
  error: string | null;
}
export interface Model {
  service: "images" | "3d" | "video";
  id: string;
  name: string;
  family: string;
  description: string;
  precision: string;
  download_gb: number;
  vram_gb: number;
  license: string;
  license_url: string;
  hub_repo: string;
  status: string;
  source: "managed" | null;
  runtime_path: string | null;
  verified: number | null;
  size_bytes: number;
  busy: boolean;
  in_use: boolean;
  steps: number;
  max_steps: number;
  max_references: number;
  transparent: boolean;
  operation: Operation | null;
}
export interface GenerationRequest {
  project_id: string;
  model_id: string;
  mode: "t2i" | "edit" | "reference";
  prompt: string;
  width: number;
  height: number;
  seed: number;
  num_inference_steps: number;
  batch_size: number;
  reference_ids: string[];
  keep_original_aspect: boolean;
  transparent_background: boolean;
}
export interface Asset {
  kind: "generated" | "reference" | "mesh" | "video" | "media-reference";
  id: string;
  project_id: string;
  name: string;
  prompt: string;
  model_id: string;
  width: number;
  height: number;
  seed: number;
  favorite: number;
  deleted: number;
  created: number;
  url: string;
  thumbnail_url: string;
  metadata: {
    settings?: GenerationRequest;
    elapsed_seconds?: number;
    [key: string]: unknown;
  };
}
export interface Job {
  id: string;
  project_id: string;
  model_id: string;
  status: string;
  phase: string;
  progress: number;
  total: number;
  completed: number;
  error: string | null;
  result_ids: string[];
  request: GenerationRequest | MeshRequest | VideoRequest;
  created: number;
}
export interface MeshRequest {
  project_id: string;
  model_id: "trellis2";
  mode: "image-to-3d" | "text-to-3d" | "simplify";
  prompt: string;
  reference_ids: string[];
  seed: number;
  num_inference_steps: number;
  resolution: number;
  texture_size: number;
  target_triangles: number;
  texture: boolean;
  background_removal: "auto" | "birefnet";
  source_mesh_id?: string;
}
export interface VideoRequest {
  project_id: string;
  model_id: "vdn-h3";
  mode: "text" | "frames" | "references" | "finish";
  prompt: string;
  quality: "light" | "medium" | "high" | "max";
  width: number;
  height: number;
  seconds: number;
  seed: number;
  preview: boolean;
  first_id?: string | null;
  last_id?: string | null;
  reference_ids: string[];
  source_video_id?: string;
}
export interface MeshStats {
  triangles: number;
  vertices: number;
  materials: number;
  has_uv: boolean;
  bounds: number[];
}
export interface MeshTexture {
  name: string;
  channel: string;
  width: number;
  height: number;
}
export interface Status {
  name: string;
  version: string;
  active_model: string | null;
  runtime_phase: string;
  data_path: string;
  hardware: {
    gpu_name: string | null;
    gpu_total_mib: number;
    gpu_used_mib: number;
    disk_free_bytes: number;
  };
}
export interface Snapshot {
  projects: Project[];
  models: Model[];
  jobs: Job[];
  status: Status | null;
}
