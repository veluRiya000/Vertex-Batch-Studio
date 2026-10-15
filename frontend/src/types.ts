export interface Batch {
  id: string; workspace_id?: string; source_batch_id?: string | null;
  project_name: string; folder: string; phase: string; created_at: string; updated_at: string;
  archived: boolean; job_name: string | null; cloud_state: string | null;
  last_error: string | null; image_output_dir: string | null;
  counts?: Record<string, number>; actual_output_uri?: string | null;
}
export interface TaskInput {
  name: string; prompt: string; refs: string[]; temperature: number | null;
  aspect_ratio: string; image_size: string; image_count: number; generation_config: Record<string, unknown>;
}
export interface Task extends TaskInput { id: string; created_at?: string | null }
export interface Reference { path: string; mime_type: string; dimensions: [number, number]; size: number; sha256: string }
export interface ImageResult { path: string; mime_type: string; sha256: string; size: number }
export interface TaskResult { total_requests?: number; completed_requests?: number; succeeded_requests?: number; task_id: string; state: string; name: string; images: ImageResult[]; error: string | null }
export interface Results { tasks: TaskResult[]; counts: Record<string, number>; final: boolean; row_errors: unknown[] }
export interface Snapshot { batch: Batch; results: Results }
export interface ModelCatalogue {
  models: { id: string; label: string; regions: string[]; source_url: string; supports_image_size: boolean; aspect_ratios: string[]; max_references: number | null; batch_image_sizes: string[]; unsupported_parameters?: string[] }[];
  source: 'official' | 'cache' | 'unavailable'; refreshing: boolean;
  fetched_at: string | null; message: string | null;
}
export interface PublicConfig { project: string; bucket: string; model: string; location: string; data_dir: string; root: string; poll_seconds: number; credentials_configured: boolean; credential_name?: string | null; authentication_mode?: 'service_account' | 'adc'; model_catalog?: ModelCatalogue; unsupported_generation_parameters?: string[] }
export interface NotificationPreferences {
  enabled: boolean; mode: 'all' | 'each'; image_batches: boolean; harness_tasks: boolean;
  include_failures: boolean; sound_enabled: boolean; sound: 'soft' | 'chime' | 'double' | 'custom';
  custom_sound_id: string | null; custom_sound_name: string | null;
}
export interface Preferences {
  notifications?: NotificationPreferences;
  theme: 'light' | 'dark'; language: 'zh-CN' | 'en'; close_to_tray: boolean;
  auto_start: boolean; start_minimized: boolean; sidebar_width: number;
}
export interface Workspace { id: string; name: string; batches: Batch[]; archived: boolean }
export type ImportOptions = { category?: string; batch_id?: string }
declare global {
  interface Window {
    studio?: {
      openCloudPage?(page: 'project' | 'storage' | 'credentials', project: string): Promise<void>;
      harnessView?(visible: boolean, offline: boolean, restoreOnly?: boolean): Promise<void>;
      api(method: string, path: string, body?: unknown): Promise<unknown>;
      image(path: string): Promise<string>;
      upload(name: string, bytes: ArrayBuffer, options: ImportOptions): Promise<Reference>;
      watch(batchId: string, callback: (snapshot: Snapshot) => void): () => void;
      chooseDirectory(): Promise<string | null>;
      openOutput(batchId: string): Promise<void>;
      window(action: 'minimize' | 'maximize' | 'hide' | 'quit'): void;
      setPreferences(value: Preferences): Promise<Preferences>;
    }
  }
}
