import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  Archive,
  ArrowDownUp,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Folder,
  FolderOpen,
  FolderPlus,
  ImagePlus,
  Images,
  Layers,
  LoaderCircle,
  Maximize2,
  Minus,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Sparkle,
  Square,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { api, upload, watchBatch } from "./api";
import { Media, Modal, Picker } from "./components";
import { SettingsPanel } from "./SettingsPanel";
import { ReferenceLibrary } from "./ReferenceLibrary";
import { LibraryPane } from "./LibraryPane";
import { ProjectMenu } from "./ProjectMenu";
import { CollapsiblePrompt } from "./CollapsiblePrompt";
import { usePreferences } from "./preferences";
import { useCloudConnection } from "./cloud-connection";
import { useTranslation } from "./i18n";
import {
  editable,
  groupBatches,
  landscape,
  matchRatio,
  phaseLabel,
  portrait,
  statusClass,
  terminal,
  workspaceId,
} from "./domain";
import type {
  Batch,
  PublicConfig,
  Reference,
  Results,
  Task,
  TaskInput,
} from "./types";

type Entry = { task: Task; batch: Batch; result?: Results["tasks"][number] };
type Preview = {
  paths: string[];
  names: string[];
  index: number;
  localPath?: string;
  localPaths?: string[];
};
const filename = (path: string) => path.split(/[\\/]/).at(-1) || path;
const referencePath = (ref: Reference, batchId?: string) =>
  "/references/file?" +
  new URLSearchParams({
    path: ref.path,
    ...(batchId ? { batch_id: batchId } : {}),
  });
const taskLabel = (entry: Entry) =>
  entry.result?.state === "succeeded"
    ? "已完成"
    : entry.result?.state === "error"
      ? "生成失败"
      : entry.result?.state === "missing"
        ? "结果缺失"
        : phaseLabel(entry.batch);
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

const studioLogo = new URL("./assets/logo.svg", import.meta.url).href;
export function Logo({ large = false }: { large?: boolean }) {
  return (
    <img
      className={large ? "studio-logo large" : "studio-logo"}
      src={studioLogo}
      alt=""
      aria-hidden
    />
  );
}
export function ModelMark() {
  const id = "star-" + useId().replace(/:/g, "");
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return (
    <span className="model-mark" aria-hidden>
      <svg width="22" height="22" viewBox="0 0 24 24">
        <defs>
          <linearGradient
            id={id}
            x1="1"
            y1="4"
            x2="23"
            y2="20"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0" stopColor="#4285F4" />
            <stop offset=".25" stopColor="#8263F4" />
            <stop offset=".5" stopColor="#E567B1" />
            <stop offset=".75" stopColor="#F5B84C" />
            <stop offset="1" stopColor="#32B992" />
            {!reduced && (
              <animateTransform
                attributeName="gradientTransform"
                type="rotate"
                from="0 12 12"
                to="360 12 12"
                dur="8s"
                repeatCount="indefinite"
              />
            )}
          </linearGradient>
        </defs>
        <path
          fill={"url(#" + id + ")"}
          d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"
        />
      </svg>
    </span>
  );
}

function TaskCard({
  entry,
  edit,
  remove,
  preview,
  action,
  openFolder,
}: {
  entry: Entry;
  edit: (entry: Entry) => void;
  remove: (entry: Entry) => void;
  preview: (value: Preview) => void;
  action: (batch: Batch, action: string) => void;
  openFolder: (batch: Batch) => void;
}) {
  const t = useTranslation();
  const { task, batch, result } = entry;
  const [index, setIndex] = useState(0);
  const images = result?.images || [];
  const current = Math.min(index, Math.max(0, images.length - 1));
  const paths = images.map(
    (_, i) => `/batches/${batch.id}/images/${task.id}/${i}`,
  );
  const color = statusClass(batch, result?.state);
  return (
    <article className="task-card" id={"task-" + task.id}>
      <div className="task-divider">
        <span>{time(task.created_at || batch.created_at)}</span>
        <span>{task.name}</span>
      </div>
      <div className="request-bubble">
        {task.refs.length > 0 && (
          <div className="request-refs">
            {task.refs.map((path, i) => (
              <button
                key={i}
                className="request-ref"
                title={path}
                onClick={() =>
                  preview({
                    paths: [referencePath({ path } as Reference, batch.id)],
                    names: [filename(path)],
                    index: 0,
                    localPath: path,
                  })
                }
              >
                <Media
                  path={referencePath({ path } as Reference, batch.id)}
                  alt={filename(path)}
                />
                <span>{i + 1}</span>
              </button>
            ))}
          </div>
        )}
        <CollapsiblePrompt text={task.prompt} />
        <div className="request-footer">
          <span>
            {task.aspect_ratio} · {task.image_size}
            {t("· 期望")} {task.image_count || 1}
            {t("张")}
          </span>
          <button className="text-button" onClick={() => edit(entry)}>
            <Copy size={13} />
            {editable(batch) ? t("编辑") : t("再次使用")}
          </button>
          {editable(batch) && (
            <button
              className="icon-button"
              aria-label={t("删除任务 ") + task.name}
              onClick={() => remove(entry)}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>
      <div className="response-area">
        <div className="response-heading">
          <Logo />
          <span>Vertex Studio</span>
          <span className={"status-tag " + color}>
            <i />
            {t(taskLabel(entry))}
          </span>
          {images.length > 0 && (
            <span className="image-total">
              {images.length}
              {t("张图片")}
            </span>
          )}
        </div>
        {images.length > 0 ? (
          <>
            <div
              className={
                "output-gallery " + (images.length === 1 ? "single" : "")
              }
            >
              <button
                className="main-output"
                onClick={() =>
                  preview({
                    paths,
                    names: images.map(
                      (_, i) => `${task.name} · ${i + 1}/${images.length}`,
                    ),
                    index: current,
                    localPaths: images.map((image) => image.path),
                  })
                }
                aria-label={t("放大预览 ") + task.name}
              >
                <Media
                  path={paths[current]}
                  alt={`${task.name} 第 ${current + 1} 张`}
                />
                <span className="expand-hint">
                  <Maximize2 size={16} />
                </span>
              </button>
              {images.length > 1 && (
                <div className="output-thumbnails">
                  {paths.map((path, i) => (
                    <button
                      key={i}
                      className={current === i ? "selected" : ""}
                      onClick={() => setIndex(i)}
                      aria-label={t("查看第 ") + (i + 1) + t(" 张")}
                      aria-pressed={current === i}
                    >
                      <Media path={path} alt={t("缩略图 ") + (i + 1)} />
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="result-actions">
              <button className="text-button" onClick={() => openFolder(batch)}>
                <FolderOpen size={14} />
                {window.studio ? t("打开输出文件夹") : t("复制输出路径")}
              </button>
              <button className="text-button" onClick={() => edit(entry)}>
                <RefreshCw size={13} />
                {t("再次使用")}
              </button>
            </div>
          </>
        ) : (
          <div className={"waiting-output " + color}>
            {(color === "generating" || color === "uploading") ? (
              <LoaderCircle className="spin" size={18} />
            ) : color === "failed" ? (
              <X size={18} />
            ) : (
              <Images size={18} />
            )}
            <span>
              {result?.error ||
                (editable(batch)
                  ? t("任务已保存，提交批次后开始生成")
                  : taskLabel(entry))}
            </span>
          </div>
        )}
        {batch.last_error && <p className="task-error">{batch.last_error}</p>}
        {!editable(batch) && (
          <div className="result-actions">
            {(batch.job_name || ["submitting", "submission_unknown"].includes(batch.phase)) && (
              <button className="text-button" onClick={() => action(batch, "poll")}>
                <RefreshCw size={13} />{t("刷新结果")}
              </button>
            )}
            {terminal(batch) && (
              <button
                className="text-button"
                onClick={() => action(batch, "extract")}
              >
                {t("重新解码")}
              </button>
            )}
            {["failed", "completed_with_errors"].includes(batch.phase) && (
              <button
                className="text-button"
                onClick={() => action(batch, "retry")}
              >
                {t("重试失败任务")}
              </button>
            )}
            {["upload_failed", "submission_failed"].includes(batch.phase) && (
              <button
                className="text-button"
                onClick={() => action(batch, "submit")}
              >
                {t("重新提交本轮")}
              </button>
            )}
            {!terminal(batch) && (
              <button
                className="text-button"
                onClick={() => action(batch, "cancel")}
              >
                {t("取消本轮")}
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export default function App() {
  const t = useTranslation();
  const { preferences, update: updatePreferences } = usePreferences();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [taskMap, setTaskMap] = useState<Record<string, Task[]>>({});
  const [results, setResults] = useState<Record<string, Results>>({});
  const [config, setConfig] = useState<PublicConfig>();
  const [activeId, setActiveId] = useState(
    localStorage.getItem("vbs-workspace") || "",
  );
  const [references, setReferences] = useState<Reference[]>([]);
  const [category, setCategory] = useState("styles");
  const [selected, setSelected] = useState<Reference[]>([]);
  const [prompt, setPrompt] = useState("");
  const [ratio, setRatio] = useState("16:9");
  const [size, setSize] = useState("1K");
  const [count, setCount] = useState("1");
  const [temperature, setTemperature] = useState("default");
  const [editing, setEditing] = useState<Entry>();
  const [sidebarWidth, setSidebarWidth] = useState(preferences.sidebar_width);
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 690);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [resizing, setResizing] = useState(false);
  const [treeCollapsed, setTreeCollapsed] = useState(false);
  const resizeStart = useRef<{ x: number; width: number } | undefined>(
    undefined,
  );
  const widthRef = useRef(sidebarWidth),
    lastWidth = useRef(
      preferences.sidebar_width > 48 ? preferences.sidebar_width : 258,
    );
  const sidebar = narrow ? drawerOpen : sidebarWidth > 48;
  const paneWidth = narrow ? 36 : Math.max(36, sidebarWidth);
  const [queue, setQueue] = useState(() => window.innerWidth > 990);
  const [queueAll, setQueueAll] = useState(false);
  const [sortName, setSortName] = useState(false);
  const [projectMenu, setProjectMenu] = useState<{ id: string; x: number; y: number }>();
  const closeProjectMenu = useCallback(() => setProjectMenu(undefined), []);
  const [modal, setModal] = useState<
    "new" | "rename" | "settings" | "about" | "output" | null
  >(null);
  const [newName, setNewName] = useState("");
  const [renameProject, setRenameProject] = useState<{ id: string; name: string }>();
  const [output, setOutput] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const cloudConnection = useCloudConnection(config, connected);
  const [notice, setNotice] = useState<{ message: string; error: boolean }>();
  const [dragging, setDragging] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const referenceInput = useRef<HTMLInputElement>(null);
  const customInput = useRef<HTMLInputElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stamps = useRef<Record<string, string>>({});
  const pending = useRef(new Set<string>());
  const inAction = useRef(false);
  const notify = useCallback(
    (message: string, error = false) => setNotice({ message, error }),
    [],
  );
  useEffect(() => {
    if (!resizing) {
      setSidebarWidth(preferences.sidebar_width);
      widthRef.current = preferences.sidebar_width;
      if (preferences.sidebar_width > 48)
        lastWidth.current = preferences.sidebar_width;
    }
  }, [preferences.sidebar_width]);
  useEffect(() => {
    const resize = () => setNarrow(window.innerWidth <= 690);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (resizing) {
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    }
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [resizing]);
  function saveWidth(value: number) {
    widthRef.current = value;
    setSidebarWidth(value);
    if (value > 48) lastWidth.current = value;
    void updatePreferences({ sidebar_width: value }).catch((error) =>
      notify(error.message, true),
    );
  }
  function toggleSidebar() {
    if (narrow) setDrawerOpen(!drawerOpen);
    else saveWidth(sidebar ? 0 : lastWidth.current);
  }

  const refresh = useCallback(async () => {
    const values = await api<Batch[]>("/batches");
    // HTTP is authoritative; don't release an optimistic submission lock until the worker changes phase.
    const visible = values.map((batch) => {
      if (pending.current.has(batch.id) && (!editable(batch) || batch.last_error))
        pending.current.delete(batch.id);
      return pending.current.has(batch.id)
        ? { ...batch, phase: "submitting" }
        : batch;
    });
    setBatches(visible);
    setConnected(true);
    const changed = values.filter(
      (batch) => stamps.current[batch.id] !== batch.updated_at,
    );
    for (let i = 0; i < changed.length; i += 4) {
      await Promise.all(
        changed.slice(i, i + 4).map(async (batch) => {
          const [tasks, report] = await Promise.all([
            api<Task[]>(`/batches/${batch.id}/tasks`),
            api<Results>(`/batches/${batch.id}/results`),
          ]);
          setTaskMap((old) => ({ ...old, [batch.id]: tasks }));
          setResults((old) => ({ ...old, [batch.id]: report }));
          stamps.current[batch.id] = batch.updated_at;
        }),
      );
    }
    return visible;
  }, []);
  useEffect(() => {
    let alive = true;
    void api<PublicConfig>("/config")
      .then((value) => {
        if (alive) setConfig(value);
      })
      .catch((error) => notify(error.message, true));
    const tick = () =>
      refresh().catch(() => {
        if (alive) setConnected(false);
      });
    void tick();
    const timer = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [refresh, notify]);
  const workspaces = groupBatches(batches).filter(
    (workspace) => !workspace.archived,
  );
  const archivedProjects = groupBatches(batches).filter((item) => item.archived);
  const workspace = workspaces.find((item) => item.id === activeId);
  const rounds = workspace?.batches.filter((batch) => !batch.archived) || [];
  const latest = rounds.at(-1);
  const draft = [...rounds].reverse().find(editable);
  const entriesFor = (values: Batch[]) =>
    values.flatMap((batch) =>
      (taskMap[batch.id] || []).map((task) => ({
        batch,
        task,
        result: results[batch.id]?.tasks.find(
          (item) => item.task_id === task.id,
        ),
      })),
    );
  const entries = entriesFor(rounds);
  const queued = entriesFor(
    queueAll ? batches.filter((batch) => !batch.archived) : rounds,
  ).sort((a, b) =>
    (a.task.created_at || a.batch.created_at).localeCompare(
      b.task.created_at || b.batch.created_at,
    ),
  );
  const filteredRefs = references.filter((ref) =>
    ref.path.startsWith("references/" + category + "/"),
  );
  const roundIds = rounds.map((batch) => batch.id).join(",");
  useEffect(() => {
    if (connected && !workspace) setActiveId(workspaces[0]?.id || "");
  }, [activeId, workspace?.id, workspaces.length, connected]);
  useEffect(() => {
    if (activeId) localStorage.setItem("vbs-workspace", activeId);
  }, [activeId]);
  useEffect(() => {
    let alive = true;
    void api<Reference[]>("/references")
      .then((value) => {
        if (alive) setReferences(value);
      })
      .catch((error) => notify(error.message, true));
    return () => {
      alive = false;
    };
  }, [notify]);
  useEffect(() => {
    const stops = roundIds
      .split(",")
      .filter(Boolean)
      .map((id) =>
        watchBatch(id, (snapshot) => {
          if (!editable(snapshot.batch) || snapshot.batch.last_error) pending.current.delete(id);
          const batch = pending.current.has(id)
            ? { ...snapshot.batch, phase: "submitting" }
            : snapshot.batch;
          setBatches((old) =>
            old.map((value) => (value.id === id ? batch : value)),
          );
          setResults((old) => ({ ...old, [id]: snapshot.results }));
        }),
      );
    return () => stops.forEach((stop) => stop());
  }, [roundIds]);
  useLayoutEffect(() => {
    if (textarea.current) {
      textarea.current.style.height = "0px";
      textarea.current.style.height = textarea.current.scrollHeight + "px";
    }
  }, [prompt]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(
      () => setNotice(undefined),
      notice.error ? 8000 : 3500,
    );
    return () => clearTimeout(timer);
  }, [notice]);
  function jump(entry: Entry) {
    setTreeCollapsed(false);
    setActiveId(workspaceId(entry.batch, batches));
    setTimeout(
      () =>
        document
          .getElementById("task-" + entry.task.id)
          ?.scrollIntoView({ behavior: "smooth", block: "center" }),
      100,
    );
  }
  function switchWorkspace(id: string) {
    if (id === activeId) return;
    setTreeCollapsed(false);
    setActiveId(id);
    setPrompt("");
    setSelected([]);
    setEditing(undefined);
  }
  async function run(action: () => Promise<void>) {
    if (inAction.current) return;
    inAction.current = true;
    setBusy(true);
    try {
      await action();
    } catch (error) {
      notify(error instanceof Error ? error.message : t("操作未完成"), true);
    } finally {
      inAction.current = false;
      setBusy(false);
    }
  }
  async function ensureDraft(): Promise<Batch> {
    if (draft && !pending.current.has(draft.id)) return draft;
    if (!latest) throw new Error(t("请先新建一个项目"));
    const next = await api<Batch>("/batches", "POST", {
      project_name: workspace!.name,
      source_batch_id: latest.id,
      image_output_dir: latest.image_output_dir,
    });
    setBatches((old) => [...old, next]);
    return next;
  }
  async function addFiles(files: File[], global: boolean) {
    await run(async () => {
      if (!files.length) return;
      if (!global && selected.length + files.length > 14)
        throw new Error(t("一个任务最多使用 14 张参考图"));
      const batch = global ? undefined : await ensureDraft();
      const added: Reference[] = [];
      for (const file of files)
        added.push(
          await upload(file, global ? { category } : { batch_id: batch!.id }),
        );
      if (global) setReferences(await api<Reference[]>("/references"));
      else
        setSelected((old) =>
          [...old, ...added].filter(
            (ref, i, all) =>
              all.findIndex((item) => item.path === ref.path) === i,
          ),
        );
      notify(global ? t("参考图已加入公共图库") : t("参考图已加入当前任务"));
    });
  }
  function selectRef(ref: Reference) {
    if (selected.some((item) => item.path === ref.path)) return;
    if (selected.length >= 14) {
      notify(t("一个任务最多使用 14 张参考图"), true);
      return;
    }
    setSelected((old) => [...old, ref]);
  }
  async function send() {
    await run(async () => {
      if (!prompt.trim()) throw new Error(t("写下提示词后再加入任务"));
      const batch =
        editing && editable(editing.batch)
          ? editing.batch
          : await ensureDraft();
      const refs: string[] = [];
      for (const ref of selected) {
        if (
          ref.path.startsWith("batches/") &&
          !ref.path.startsWith("batches/" + batch.folder + "/")
        ) {
          if (!config) throw new Error(t("本地配置尚未加载"));
          const copy = await api<Reference>("/references/import", "POST", {
            source: config.data_dir + "/" + ref.path,
            batch_id: batch.id,
          });
          refs.push(copy.path);
        } else refs.push(ref.path);
      }
      const value: TaskInput = {
        name: editing?.task.name || prompt.trim().split("\n")[0].slice(0, 32),
        prompt,
        refs,
        temperature: temperature === "default" ? null : Number(temperature),
        aspect_ratio: ratio === "reference" ? matchRatio(selected[0]) : ratio,
        image_size: size,
        image_count: Number(count),
        generation_config: editing?.task.generation_config || {},
      };
      if (editing && editable(editing.batch))
        await api(
          `/batches/${batch.id}/tasks/${editing.task.id}`,
          "PUT",
          value,
        );
      else await api(`/batches/${batch.id}/tasks`, "POST", value);
      delete stamps.current[batch.id];
      await refresh();
      setPrompt("");
      setSelected([]);
      setEditing(undefined);
      setTimeout(
        () =>
          scroller.current?.scrollTo({
            top: scroller.current.scrollHeight,
            behavior: "smooth",
          }),
        100,
      );
      notify(t("任务已保存，提交批次后开始生成"));
    });
  }
  async function reuse(entry: Entry) {
    await run(async () => {
      const all = await api<Reference[]>(
        "/references?batch_id=" + entry.batch.id,
      );
      setSelected(
        entry.task.refs.map(
          (path) =>
            all.find((ref) => ref.path === path) || {
              path,
              mime_type: "image/png",
              size: 0,
              sha256: "",
              dimensions: [0, 0],
            },
        ),
      );
      setPrompt(entry.task.prompt);
      setRatio(entry.task.aspect_ratio);
      setSize(entry.task.image_size);
      setCount(String(entry.task.image_count || 1));
      setTemperature(
        entry.task.temperature === null
          ? "default"
          : String(entry.task.temperature),
      );
      setEditing(entry);
      switchWorkspaceForEdit(entry);
      textarea.current?.focus();
    });
  }
  function switchWorkspaceForEdit(entry: Entry) {
    setActiveId(workspaceId(entry.batch, batches));
  }
  async function batchAction(batch: Batch, action: string) {
    await run(async () => {
      const result = await api<Batch>(`/batches/${batch.id}/${action}`, "POST");
      if (action === "clone" || action === "retry") {
        setBatches((old) => [...old, result]);
        setActiveId(result.workspace_id || activeId);
      }
      delete stamps.current[batch.id];
      await refresh();
      notify(
        action === "retry"
          ? t("失败任务已复制到新一轮，等待提交")
          : t("操作已安排"),
      );
    });
  }
  async function submit() {
    if (!draft) return;
    await run(async () => {
      if (!taskMap[draft.id]?.length)
        throw new Error(t("加入至少一个任务后再提交"));
      pending.current.add(draft.id);
      setBatches((old) =>
        old.map((batch) =>
          batch.id === draft.id ? { ...batch, phase: "submitting" } : batch,
        ),
      );
      try {
        await api(`/batches/${draft.id}/submit`, "POST");
        notify(t("批次已加入提交队列"));
      } catch (error) {
        pending.current.delete(draft.id);
        throw error;
      } finally {
        await refresh();
      }
    });
  }
  async function openFolder(batch: Batch) {
    await run(async () => {
      if (window.studio) await window.studio.openOutput(batch.id);
      else {
        await navigator.clipboard.writeText(
          batch.image_output_dir ||
            config!.data_dir + (batch.archived ? "/archive/" : "/batches/") + batch.folder + "/outputs/images",
        );
        notify(t("输出路径已复制"));
      }
    });
  }
  const sortedWorkspaces = sortName
    ? [...workspaces].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"))
    : workspaces;
  const currentRefsBatch = (ref: Reference) =>
    batches.find((batch) =>
      ref.path.startsWith("batches/" + batch.folder + "/"),
    )?.id;

  return (
    <div
      className={
        "studio-shell " +
        (resizing ? "resizing " : "") +
        (!sidebar ? "sidebar-hidden " : "") +
        (!queue ? "queue-hidden" : "")
      }
      style={{
        gridTemplateColumns:
          paneWidth +
          "px minmax(0,1fr)" +
          (queue && !narrow && window.innerWidth > 990 ? " 218px" : ""),
      }}
    >
      <header className="titlebar">
        <div className="brand">
          <Logo />
          <strong>
            Vertex<span>Studio</span>
          </strong>
        </div>
        <div className="top-actions">
          <button
            onClick={() => {
              setNewName("");
              setModal("new");
            }}
          >
            {t("新建项目")}
          </button>
          <button onClick={toggleSidebar}>{t("视图")}</button>
          <button onClick={() => setModal("about")}>{t("关于")}</button>
        </div>
        <div className="titlebar-space" />
        <button className={"connection " + (cloudConnection.state === "online" ? "online" : "offline")}
          title={t("检查 Google Cloud 连接")} aria-label={t("Google Cloud：") + t(cloudConnection.label)}
          disabled={!connected || cloudConnection.state === "checking"}
          onClick={() => void run(() => cloudConnection.check())}>
          <i />
          {t(cloudConnection.label)}
        </button>
        {window.studio && (
          <div className="window-buttons">
            <button
              aria-label={t("最小化")}
              onClick={() => window.studio!.window("minimize")}
            >
              <Minus size={14} />
            </button>
            <button
              aria-label={t("最大化")}
              onClick={() => window.studio!.window("maximize")}
            >
              <Square size={12} />
            </button>
            <button
              aria-label={t("关闭到托盘")}
              onClick={() => window.studio!.window("hide")}
            >
              <X size={16} />
            </button>
          </div>
        )}
      </header>
      {narrow && sidebar && (
        <button
          className="sidebar-scrim"
          aria-label={t("关闭侧栏遮罩")}
          onClick={() => setDrawerOpen(false)}
        />
      )}
      {
        <aside
          className={
            "sidebar resizable-sidebar " +
            (sidebarWidth < 160 && !narrow ? "compact " : "") +
            (!sidebar ? "collapsed" : "")
          }
          style={{
            width:
              narrow && drawerOpen ? Math.max(220, sidebarWidth) : paneWidth,
          }}
        >
          <div
            className="sidebar-content"
            hidden={!sidebar}
            style={{
              opacity: narrow
                ? 1
                : Math.min(1, Math.max(0, (sidebarWidth - 64) / 100)),
            }}
          >
            <LibraryPane><ReferenceLibrary
              references={filteredRefs}
              category={category}
              setCategory={setCategory}
              busy={busy}
              chooseFiles={() => referenceInput.current?.click()}
              importFiles={(files) => void addFiles(files, true)}
              add={selectRef}
              remove={async (ref) => {
                const value = await api<Reference[]>("/references?" + new URLSearchParams({ path: ref.path }), "DELETE");
                setReferences(value);
                setSelected((old) => old.filter((item) => item.path !== ref.path));
              }}
              preview={(items, index) =>
                setPreview({
                  paths: items.map((ref) => referencePath(ref)),
                  names: items.map((ref) => filename(ref.path)),
                  index,
                  localPaths: items.map(
                    (ref) => (config?.data_dir || "") + "/" + ref.path,
                  ),
                })
              }
              reorder={async (paths) => {
                setReferences(
                  await api<Reference[]>("/references/order", "PUT", {
                    category,
                    paths,
                  }),
                );
              }}
              error={(message) => notify(message, true)}
            /></LibraryPane>
            <section className="project-library">
              <div className="section-heading">
                <span>
                  {t("项目")}
                  <small>{workspaces.length}</small>
                </span>
                <div>
                  <button
                    className={"icon-button " + (sortName ? "active" : "")}
                    aria-label={t("切换项目排序")}
                    title={sortName ? t("按名称排序") : t("按最近创建排序")}
                    onClick={() => setSortName(!sortName)}
                  >
                    <ArrowDownUp size={15} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={t("新建项目")}
                    onClick={() => {
                      setNewName("");
                      setModal("new");
                    }}
                  >
                    <FolderPlus size={17} />
                  </button>
                </div>
              </div>
              <nav className="project-list">
                {sortedWorkspaces.map((item) => (
                  <div
                    key={item.id}
                    className={
                      "project " + (activeId === item.id ? "selected" : "")
                    }
                  >
                    <button
                      className="project-title"
                      onContextMenu={(event) => {
                        event.preventDefault();
                        setProjectMenu({ id: item.id, x: event.clientX, y: event.clientY });
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                          event.preventDefault();
                          const box = event.currentTarget.getBoundingClientRect();
                          setProjectMenu({ id: item.id, x: box.left + 20, y: box.bottom });
                        }
                      }}
                      aria-expanded={activeId === item.id && !treeCollapsed}
                      onClick={() =>
                        activeId === item.id
                          ? setTreeCollapsed(!treeCollapsed)
                          : switchWorkspace(item.id)
                      }
                    >
                      <Folder size={17} />
                      <span>{item.name}</span>
                      {activeId === item.id && !treeCollapsed ? (
                        <ChevronDown size={13} />
                      ) : (
                        <ChevronRight size={13} />
                      )}
                    </button>
                    {activeId === item.id && !treeCollapsed && (
                      <div className="project-tasks">
                        {entries.map((entry) => (
                          <button
                            key={entry.task.id}
                            onClick={() => jump(entry)}
                            title={entry.task.name}
                          >
                            <i
                              className={
                                "status-dot " +
                                statusClass(entry.batch, entry.result?.state)
                              }
                            />
                            <span>{entry.task.name}</span>
                          </button>
                        ))}
                        {!entries.length && (
                          <span className="project-no-tasks">
                            {t("还没有任务")}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </nav>
            </section>
          </div>
          <div className="sidebar-bottom">
            <button
              className="text-button"
              onClick={() => setModal("settings")}
            >
              <Settings2 size={16} />
              {t("设置")}
            </button>
            <button
              className="icon-button"
              aria-label={sidebar ? t("收起侧栏") : t("展开侧栏")}
              title={sidebar ? t("收起侧栏") : t("展开侧栏")}
              onClick={toggleSidebar}
            >
              {sidebar ? (
                <PanelLeftClose size={17} />
              ) : (
                <PanelLeftOpen size={17} />
              )}
            </button>
          </div>
          <div
            className="sidebar-resize"
            role="separator"
            aria-label={t("调整侧栏宽度")}
            aria-orientation="vertical"
            aria-valuemin={0}
            aria-valuemax={420}
            aria-valuenow={sidebarWidth}
            tabIndex={0}
            onPointerDown={(event) => {
              if (narrow) return;
              event.preventDefault();
              event.currentTarget.setPointerCapture(event.pointerId);
              resizeStart.current = {
                x: event.clientX,
                width: Math.max(36, sidebarWidth),
              };
              setResizing(true);
            }}
            onPointerMove={(event) => {
              if (!resizeStart.current) return;
              const value = Math.max(
                0,
                Math.min(
                  420,
                  Math.round(
                    resizeStart.current.width +
                      event.clientX -
                      resizeStart.current.x,
                  ),
                ),
              );
              widthRef.current = value;
              setSidebarWidth(value);
            }}
            onPointerUp={(event) => {
              if (!resizeStart.current) return;
              resizeStart.current = undefined;
              setResizing(false);
              event.currentTarget.releasePointerCapture(event.pointerId);
              saveWidth(widthRef.current);
            }}
            onPointerCancel={() => {
              resizeStart.current = undefined;
              setResizing(false);
              saveWidth(widthRef.current);
            }}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowLeft"
                  ? sidebarWidth - 20
                  : event.key === "ArrowRight"
                    ? sidebarWidth + 20
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? 420
                        : null;
              if (next !== null) {
                event.preventDefault();
                saveWidth(Math.max(0, Math.min(420, next)));
              }
            }}
          />
        </aside>
      }
      <main
        className={"workspace " + (!entries.length ? "empty-workspace" : "")}
      >
        <div className="workspace-heading">
          <div>
            <span>{workspace?.name || t("创作空间")}</span>
            {latest && <small>{latest.folder.slice(0, 8)}</small>}
          </div>
          <button
            className={"icon-button " + (queue ? "active" : "")}
            aria-label={queue ? t("收起生成队列") : t("展开生成队列")}
            onClick={() => {
              setQueue(!queue);
              if (narrow) setDrawerOpen(false);
            }}
          >
            <Layers size={18} />
          </button>
        </div>
        <div className="conversation" ref={scroller}>
          {entries.map((entry) => (
            <TaskCard
              key={entry.task.id}
              entry={entry}
              edit={(entry) => void reuse(entry)}
              remove={(entry) =>
                void run(async () => {
                  await api(
                    `/batches/${entry.batch.id}/tasks/${entry.task.id}`,
                    "DELETE",
                  );
                  delete stamps.current[entry.batch.id];
                  await refresh();
                  notify(t("任务已删除"));
                })
              }
              preview={(value) =>
                setPreview({
                  ...value,
                  localPath:
                    value.localPath &&
                    !/^(?:[A-Za-z]:|\\\\)/.test(value.localPath)
                      ? (config?.data_dir || "") + "/" + value.localPath
                      : value.localPath,
                })
              }
              action={(batch, action) => void batchAction(batch, action)}
              openFolder={(batch) => void openFolder(batch)}
            />
          ))}
        </div>
        <div className="composer-zone">
          <div className="composer-context">
            <Folder size={15} />
            {workspaces.length ? (
              <Picker
                label={t("当前项目")}
                value={activeId}
                onChange={switchWorkspace}
                options={workspaces.map((item) => ({
                  value: item.id,
                  label: item.name,
                }))}
              />
            ) : (
              <button className="text-button" onClick={() => setModal("new")}>
                {t("选择或新建项目")}
              </button>
            )}
            <span className="context-space" />
            {latest && <button className="text-button" onClick={() => void openFolder(latest)}>
              <FolderOpen size={14} />{t("打开输出目录")}
            </button>}
            {latest && (
              <button
                className="text-button output-setting"
                onClick={() => {
                  setOutput(latest.image_output_dir || "");
                  setModal("output");
                }}
              >
                <FolderOpen size={13} />
                {t("设置输出目录")}
              </button>
            )}
          </div>
          {editing && (
            <div className="editing-banner">
              <span>
                {editable(editing.batch) ? t("正在编辑") : t("再次使用")} ·{" "}
                {editing.task.name}
              </span>
              <button
                className="icon-button"
                aria-label={t("取消编辑")}
                onClick={() => {
                  setEditing(undefined);
                  setPrompt("");
                  setSelected([]);
                }}
              >
                <X size={13} />
              </button>
            </div>
          )}
          <div
            className={"composer " + (dragging ? "dragging" : "")}
            onDragOver={(event) => {
              if (
                Array.from(event.dataTransfer.types).includes(
                  "application/x-vbs-library-sort",
                )
              )
                return;
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node))
                setDragging(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (event.dataTransfer.getData("application/x-vbs-library-sort"))
                return;
              const raw = event.dataTransfer.getData(
                  "application/x-vbs-reference",
                ),
                reorder = event.dataTransfer.getData("application/x-vbs-order");
              if (raw) {
                try {
                  selectRef(JSON.parse(raw));
                } catch {
                  notify(t("无法读取拖入的参考图"), true);
                }
              } else if (reorder)
                setSelected((old) => {
                  const copy = [...old],
                    from = Number(reorder);
                  if (from >= 0 && from < copy.length)
                    copy.push(copy.splice(from, 1)[0]);
                  return copy;
                });
              else if (event.dataTransfer.files.length)
                void addFiles(Array.from(event.dataTransfer.files), false);
            }}
          >
            {selected.length > 0 && (
              <div className="composer-refs">
                {selected.map((ref, i) => (
                  <div
                    key={ref.path}
                    className="composer-ref"
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData(
                        "application/x-vbs-order",
                        String(i),
                      );
                      event.stopPropagation();
                    }}
                    onDrop={(event) => {
                      const from = event.dataTransfer.getData(
                        "application/x-vbs-order",
                      );
                      if (from) {
                        event.preventDefault();
                        event.stopPropagation();
                        setDragging(false);
                        setSelected((old) => {
                          const copy = [...old];
                          copy.splice(i, 0, copy.splice(Number(from), 1)[0]);
                          return copy;
                        });
                      }
                    }}
                  >
                    <button
                      className="ref-preview"
                      aria-label={t("预览参考图 ") + (i + 1)}
                      onClick={() =>
                        setPreview({
                          paths: [referencePath(ref, currentRefsBatch(ref))],
                          names: [filename(ref.path)],
                          index: 0,
                          localPath: (config?.data_dir || "") + "/" + ref.path,
                        })
                      }
                    >
                      <Media
                        path={referencePath(ref, currentRefsBatch(ref))}
                        alt={filename(ref.path)}
                      />
                    </button>
                    <span className="ref-number">{i + 1}</span>
                    <button
                      className="ref-remove"
                      aria-label={t("移除参考图 ") + (i + 1)}
                      onClick={() =>
                        setSelected((old) => old.filter((_, j) => i !== j))
                      }
                    >
                      <X size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <textarea
              ref={textarea}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t("描绘你想生成的画面，也可以拖入参考图…")}
              aria-label={t("提示词")}
              rows={2}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <div className="composer-toolbar">
              <button
                className="icon-button add-reference"
                title={t("导入当前任务参考图")}
                aria-label={t("导入当前任务参考图")}
                onClick={() => customInput.current?.click()}
                disabled={!workspace || busy}
              >
                <Plus size={19} />
              </button>
              <Picker
                label={t("模型")}
                value="nano"
                onChange={() => {}}
                icon={<ModelMark />}
                options={[{ value: "nano", label: "Nano Banana 2" }]}
                className="model-picker"
              />
              <span className="toolbar-space" />
              <Picker
                label={t("比例")}
                value={ratio}
                onChange={(value) => {
                  if (value === "reference") {
                    try {
                      matchRatio(selected[0]);
                    } catch (error) {
                      notify((error as Error).message, true);
                      return;
                    }
                  }
                  setRatio(value);
                }}
                groups={[
                  {
                    label: t("横屏"),
                    options: landscape.map((value) => ({
                      value,
                      label: value,
                    })),
                  },
                  {
                    label: t("竖屏"),
                    options: portrait.map((value) => ({ value, label: value })),
                  },
                ]}
                options={[
                  { value: "1:1", label: t("1:1 · 方形") },
                  { value: "reference", label: t("匹配参考图") },
                ]}
              />
              <Picker
                label={t("分辨率")}
                value={size}
                onChange={setSize}
                options={["512", "1K", "2K", "4K"].map((value) => ({
                  value,
                  label: value,
                }))}
              />
              <Picker
                label={t("图片数量")}
                value={count}
                onChange={setCount}
                options={["1", "2", "3", "4"].map((value) => ({
                  value,
                  label: value,
                }))}
                icon={<Layers size={16} />}
                unit={t("张")}
                className="count-picker"
              />
              <Picker
                label={t("温度")}
                value={temperature}
                onChange={setTemperature}
                icon={<><SlidersHorizontal size={15} /><span className="picker-caption">{t("温度")}</span></>}
                title={t("控制生成的随机程度；默认使用模型设置")}
                options={[
                  { value: "default", label: t("默认") },
                  { value: "0.5", label: "0.5" },
                  { value: "1", label: "1.0" },
                  { value: "1.5", label: "1.5" },
                  { value: "2", label: "2.0" },
                ]}
                className="temperature-picker"
              />
              <button
                className="add-task"
                onClick={() => void send()}
                disabled={busy || !workspace || !prompt.trim()}
              >
                {busy ? (
                  <LoaderCircle size={16} className="spin" />
                ) : (
                  <Plus size={16} />
                )}
                <span>
                  {editing && editable(editing.batch)
                    ? t("保存修改")
                    : t("加入任务")}
                </span>
              </button>
            </div>
            {dragging && (
              <div className="drop-overlay">
                <ImagePlus size={25} />
                <span>{t("放开即可加入参考图")}</span>
              </div>
            )}
          </div>
          <div className="submit-bar">
            <span>
              {draft
                ? (taskMap[draft.id]?.length || 0) + t(" 个任务待提交")
                : entries.length
                  ? ""
                  : t("Ctrl + Enter 加入任务")}
              {selected.length > 0 && " · " + selected.length + t(" 张参考图")}
            </span>
            {draft && (
              <button
                className="primary-button"
                onClick={() => void submit()}
                disabled={busy || !taskMap[draft.id]?.length}
              >
                <UploadCloud size={16} />
                {t("提交批次")}
              </button>
            )}
            {latest && !terminal(latest) && (!editable(latest) || !!latest.last_error) && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void batchAction(latest, "cancel")}
              >
                {t("取消本轮")}
              </button>
            )}
          </div>
        </div>
      </main>
      {queue && (
        <aside className="queue">
          <div className="section-heading">
            <span>
              <Layers size={16} />
              {t("生成队列")}
            </span>
            <small>{queued.length}</small>
          </div>
          <div className="queue-toggle">
            <button
              className={!queueAll ? "active" : ""}
              onClick={() => setQueueAll(false)}
            >
              {t("当前项目")}
            </button>
            <button
              className={queueAll ? "active" : ""}
              onClick={() => setQueueAll(true)}
            >
              {t("全部")}
            </button>
          </div>
          <div className="queue-list">
            {queued.map((entry, i) => (
              <button
                key={entry.task.id}
                className="queue-item"
                onClick={() => jump(entry)}
              >
                <span className="queue-number">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="queue-item-body">
                  <strong title={entry.task.name}>{entry.task.name}</strong>
                  <span className="queue-meta"><small>
                    {time(entry.task.created_at || entry.batch.created_at)}
                  </small>
                  <span
                    className={
                      "queue-state " +
                      statusClass(entry.batch, entry.result?.state)
                    }
                  >
                    <i />
                    {t(taskLabel(entry))}
                  </span></span>
                </span>
              </button>
            ))}
          </div>
          <div className="queue-footer">
            <i className="status-dot completed" />
            <span>{t("图片返回后自动保存")}</span>
          </div>
        </aside>
      )}
      <input
        ref={referenceInput}
        type="file"
        hidden
        multiple
        accept="image/png,image/jpeg,image/webp"
        onChange={(event) => {
          void addFiles(Array.from(event.target.files || []), true);
          event.target.value = "";
        }}
      />
      <input
        ref={customInput}
        type="file"
        hidden
        multiple
        accept="image/png,image/jpeg,image/webp"
        onChange={(event) => {
          void addFiles(Array.from(event.target.files || []), false);
          event.target.value = "";
        }}
      />
      {modal === "new" && (
        <Modal title={t("新建项目")} close={() => setModal(null)}>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                const batch = await api<Batch>("/batches", "POST", {
                  project_name: newName,
                });
                setBatches((old) => [...old, batch]);
                switchWorkspace(batch.id);
                setModal(null);
                await refresh();
                notify(t("项目已创建"));
              });
            }}
          >
            <label className="form-label">
              {t("项目名称")}
              <input
                autoFocus
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                maxLength={120}
              />
            </label>
            <button
              className="primary-button"
              disabled={busy || !newName.trim()}
              type="submit"
            >
              <FolderPlus size={16} />
              {t("创建项目")}
            </button>
          </form>
        </Modal>
      )}
      {modal === "rename" && renameProject && (
        <Modal title={t("重命名项目")} close={() => setModal(null)}>
          <form onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await api(`/workspaces/${renameProject.id}`, "PUT", { project_name: renameProject.name });
              await refresh();
              setModal(null);
              notify(t("项目已重命名"));
            });
          }}>
            <label className="form-label">{t("项目名称")}
              <input autoFocus value={renameProject.name} maxLength={80}
                onChange={(event) => setRenameProject({ ...renameProject, name: event.target.value })} />
            </label>
            <button className="primary-button" type="submit" disabled={busy || !renameProject.name.trim()}>
              <Check size={16} />{t("保存名称")}
            </button>
          </form>
        </Modal>
      )}
      {modal === "about" && (
        <Modal title={t("关于")} close={() => setModal(null)}>
          <div className="settings-summary">
            <Logo large />
            <div>
              <strong>Vertex Batch Studio</strong>
            </div>
          </div>
          <dl className="settings-list">
            <dt>{t("项目")}</dt>
            <dd>{config?.project || t("未配置")}</dd>
            <dt>{t("存储桶")}</dt>
            <dd>{config?.bucket || t("未配置")}</dd>
            <dt>{t("模型")}</dt>
            <dd>{config?.model || "Nano Banana 2"}</dd>
            <dt>{t("区域")}</dt>
            <dd>{config?.location || "global"}</dd>
            <dt>{t("凭证")}</dt>
            <dd>
              {config?.credentials_configured ? t("已配置") : t("未配置")}
            </dd>
            <dt>{t("工作目录")}</dt>
            <dd>{config?.data_dir}</dd>
          </dl>
          <div className="settings-actions">
            <button
              className="secondary-button"
              onClick={() =>
                void run(async () => {
                  await cloudConnection.check();
                  notify(t("连接正常"));
                })
              }
            >
              <RefreshCw size={15} />
              {t("检查连接")}
            </button>
          </div>
        </Modal>
      )}
      {projectMenu && (
        <ProjectMenu x={projectMenu.x} y={projectMenu.y} close={closeProjectMenu}
          rename={() => {
            const project = workspaces.find(item => item.id === projectMenu.id);
            if (project) { setRenameProject({ id: project.id, name: project.name }); setModal("rename"); }
          }}
          allowed={!busy && !!workspaces.find((item) => item.id === projectMenu.id)?.batches.every((batch) =>
            batch.archived || editable(batch) || terminal(batch) || ["upload_failed", "submission_failed"].includes(batch.phase))}
          archive={() => void run(async () => {
            await api(`/workspaces/${projectMenu.id}/archive`, "POST");
            if (activeId === projectMenu.id) { setEditing(undefined); setPrompt(""); setSelected([]); setActiveId(""); }
            await refresh();
            notify(t("项目已归档"));
          })} />
      )}
      {modal === "settings" && (
        <SettingsPanel
          config={config}
          close={() => setModal(null)}
          configured={setConfig}
          checkConnection={cloudConnection.check}
          archivedProjects={archivedProjects}
          deleteArchived={async (id) => {
            await api(`/workspaces/${id}`, "DELETE");
            await refresh();
            notify(t("归档项目已删除"));
          }}
        />
      )}
      {modal === "output" && (
        <Modal title={t("图片保存位置")} close={() => setModal(null)}>
          <label className="form-label">
            {t("输出文件夹")}
            <input
              value={output}
              onChange={(event) => setOutput(event.target.value)}
              placeholder={t("留空使用本批次 outputs/images")}
            />
          </label>
          {window.studio && (
            <button
              className="secondary-button"
              onClick={() =>
                void window.studio!.chooseDirectory().then((path) => {
                  if (path) setOutput(path);
                })
              }
            >
              <FolderOpen size={15} />
              {t("选择文件夹")}
            </button>
          )}
          <p className="form-hint">
            {t("本轮已提交时，此设置会用于下一轮。原始结果保留在对应批次中。")}
          </p>
          <button
            className="primary-button"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const batch = await ensureDraft();
                await api(`/batches/${batch.id}/output-directory`, "PUT", {
                  path: output.trim() || null,
                });
                delete stamps.current[batch.id];
                await refresh();
                setModal(null);
                notify(t("保存位置已更新"));
              })
            }
          >
            <Check size={16} />
            {t("保存")}
          </button>
        </Modal>
      )}
      {preview && (
        <Modal
          title={preview.names[preview.index]}
          close={() => setPreview(undefined)}
          wide
        >
          <div className="preview-image">
            <Media
              path={preview.paths[preview.index]}
              alt={preview.names[preview.index]}
            />
          </div>
          {preview.paths.length > 1 && (
            <div className="preview-navigation">
              <button
                className="secondary-button"
                disabled={preview.index === 0}
                onClick={() =>
                  setPreview({ ...preview, index: preview.index - 1 })
                }
              >
                {t("上一张")}
              </button>
              <span>
                {preview.index + 1} / {preview.paths.length}
              </span>
              <button
                className="secondary-button"
                disabled={preview.index === preview.paths.length - 1}
                onClick={() =>
                  setPreview({ ...preview, index: preview.index + 1 })
                }
              >
                {t("下一张")}
              </button>
            </div>
          )}
          {(preview.localPaths?.[preview.index] || preview.localPath) && (
            <p className="preview-path">
              {preview.localPaths?.[preview.index] || preview.localPath}
            </p>
          )}
        </Modal>
      )}
      {notice && (
        <div
          className={"toast " + (notice.error ? "error" : "")}
          role={notice.error ? "alert" : "status"}
        >
          {notice.error ? <X size={16} /> : <Check size={16} />}
          <span>{notice.message}</span>
          <button
            aria-label={t("关闭提示")}
            onClick={() => setNotice(undefined)}
          >
            <X size={13} />
          </button>
        </div>
      )}
    </div>
  );
}
