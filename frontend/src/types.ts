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
  request: GenerationRequest;
  created: number;
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
