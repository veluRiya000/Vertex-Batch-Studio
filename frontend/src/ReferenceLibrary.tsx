import { useEffect, useRef, useState } from "react";
import {
  GripVertical,
  ImagePlus,
  Images,
  LayoutGrid,
  List,
  Plus,
  Trash2,
} from "lucide-react";
import { Media, Modal } from "./components";
import { useTranslation } from "./i18n";
import type { Reference } from "./types";

export function ReferenceLibrary({
  references,
  category,
  setCategory,
  importFiles,
  chooseFiles,
  add,
  remove,
  preview,
  reorder,
  error,
  busy,
}: {
  references: Reference[];
  category: string;
  setCategory: (value: string) => void;
  importFiles: (files: File[]) => void;
  chooseFiles: () => void;
  add: (ref: Reference) => void;
  remove?: (ref: Reference) => Promise<void>;
  preview: (refs: Reference[], index: number) => void;
  reorder: (paths: string[]) => Promise<void>;
  error: (message: string) => void;
  busy: boolean;
}) {
  const t = useTranslation();
  const [deleting, setDeleting] = useState<Reference>(), [deleteBusy, setDeleteBusy] = useState(false), [deleteError, setDeleteError] = useState("");
  const [mode, setMode] = useState<"grid" | "list">(() => {
    try {
      return localStorage.getItem("vbs-reference-view") === "list"
        ? "list"
        : "grid";
    } catch {
      return "grid";
    }
  });
  const [items, setItems] = useState(references),
    [saving, setSaving] = useState(false);
  const [dragging, setDragging] = useState(""),
    [target, setTarget] = useState("");
  const source = useRef(""),
    suppressClick = useRef(false);
  useEffect(() => {
    if (!saving) setItems(references);
  }, [references, saving]);
  useEffect(() => {
    try {
      localStorage.setItem("vbs-reference-view", mode);
    } catch {}
  }, [mode]);
  function clearDrag() {
    source.current = "";
    setDragging("");
    setTarget("");
  }
  async function move(path: string, destination: string) {
    const from = items.findIndex((ref) => ref.path === path),
      to = items.findIndex((ref) => ref.path === destination);
    if (saving || from < 0 || to < 0 || from === to) return;
    const previous = items,
      next = [...items],
      removed = next.splice(from, 1)[0];
    next.splice(to, 0, removed);
    setItems(next);
    setSaving(true);
    try {
      await reorder(next.map((ref) => ref.path));
    } catch (e) {
      setItems(previous);
      error(e instanceof Error ? e.message : t("排序未保存"));
    } finally {
      setSaving(false);
    }
  }
  const name = (ref: Reference) => ref.path.split("/").at(-1)!;
  return (
    <section className="reference-library">
      <div className="section-heading">
        <span>
          <Images size={16} />
          {t("参考图库")}
        </span>
        <div className="reference-controls">
          <button
            className={"icon-button " + (mode === "list" ? "active" : "")}
            aria-label={t("列表模式")}
            title={t("列表模式")}
            aria-pressed={mode === "list"}
            onClick={() => setMode("list")}
          >
            <List size={15} />
          </button>
          <button
            className={"icon-button " + (mode === "grid" ? "active" : "")}
            aria-label={t("窗格模式")}
            title={t("窗格模式")}
            aria-pressed={mode === "grid"}
            onClick={() => setMode("grid")}
          >
            <LayoutGrid size={15} />
          </button>
          <button
            className="icon-button"
            onClick={chooseFiles}
            title={t("导入公共参考图")}
            aria-label={t("导入公共参考图")}
            disabled={busy}
          >
            <Plus size={17} />
          </button>
        </div>
      </div>
      <div className="category-tabs">
        {[
          ["styles", t("风格")],
          ["characters", t("人设")],
          ["scenes", t("场景")],
        ].map(([id, label]) => (
          <button
            key={id}
            className={category === id ? "active" : ""}
            onClick={() => {
              if (!saving) {
                clearDrag();
                setCategory(id);
              }
            }}
            disabled={saving}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        className={"reference-grid reference-browser " + mode + "-mode"}
        aria-busy={saving}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          if (event.dataTransfer.files.length)
            importFiles(Array.from(event.dataTransfer.files));
          else if (source.current && items.length)
            void move(source.current, items.at(-1)!.path);
          clearDrag();
        }}
      >
        {items.map((ref, index) => (
          <div
            key={ref.path}
            className={
              "reference-card " +
              (dragging === ref.path ? "drag-source " : "") +
              (target === ref.path ? "drop-target" : "")
            }
            draggable={!saving}
            onDragStart={(event) => {
              source.current = ref.path;
              suppressClick.current = true;
              setDragging(ref.path);
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData(
                "application/x-vbs-library-sort",
                ref.path,
              );
            }}
            onDragOver={(event) => {
              if (source.current) {
                event.preventDefault();
                event.stopPropagation();
                event.dataTransfer.dropEffect = "move";
                setTarget(ref.path);
              }
            }}
            onDrop={(event) => {
              if (source.current) {
                event.preventDefault();
                event.stopPropagation();
                const path = source.current;
                clearDrag();
                void move(path, ref.path);
              }
            }}
            onDragEnd={() => {
              clearDrag();
              setTimeout(() => {
                suppressClick.current = false;
              }, 0);
            }}
          >
            <button
              className="reference-preview"
              aria-label={t("预览参考图 ") + name(ref)}
              title={name(ref)}
              onClick={() => {
                if (!suppressClick.current) preview(items, index);
              }}
              onKeyDown={(event) => {
                if (
                  event.altKey &&
                  ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
                    event.key,
                  )
                ) {
                  event.preventDefault();
                  const offset = ["ArrowLeft", "ArrowUp"].includes(event.key)
                    ? -1
                    : 1;
                  const destination = items[index + offset];
                  if (destination) void move(ref.path, destination.path);
                }
              }}
            >
              {mode === "list" && (
                <GripVertical
                  className="reference-grip"
                  size={12}
                  aria-hidden
                />
              )}
              <Media
                path={
                  "/references/file?" + new URLSearchParams({ path: ref.path })
                }
                alt={name(ref)}
              />
              <span className="reference-name">{name(ref)}</span>
            </button>
            <button
              className="reference-add"
              aria-label={t("加入参考图 ") + name(ref)}
              title={t("加入参考图")}
              onClick={(event) => {
                event.stopPropagation();
                add(ref);
              }}
              draggable={false}
            >
              <Plus size={14} />
            </button>
            {remove && <button className="reference-delete" aria-label={t("删除参考图 ") + name(ref)}
              title={t("删除参考图")} disabled={busy || saving || deleteBusy} draggable={false}
              onClick={(event) => { event.stopPropagation(); setDeleteError(""); setDeleting(ref); }}>
              <Trash2 size={13} />
            </button>}
          </div>
        ))}
        {!items.length && (
          <button
            className="library-empty"
            aria-label={t("导入公共参考图")}
            onClick={chooseFiles}
          >
            <ImagePlus size={22} />
          </button>
        )}
      </div>
      {deleting && <Modal title={t("删除参考图")} close={() => { if (!deleteBusy) setDeleting(undefined) }}>
        <p className="reference-delete-message">{t("从参考图库中删除")}「{name(deleting)}」？</p>
        {deleteError && <p className="settings-error" role="alert">{deleteError}</p>}
        <div className="archive-confirm-actions">
          <button className="secondary-button" disabled={deleteBusy} onClick={() => setDeleting(undefined)}>{t("取消")}</button>
          <button className="primary-button destructive" disabled={deleteBusy} onClick={async () => {
            if (!remove || deleteBusy) return;
            setDeleteBusy(true); setDeleteError("");
            try { await remove(deleting); setDeleting(undefined) }
            catch (e) { setDeleteError(e instanceof Error ? e.message : t("删除失败")) }
            finally { setDeleteBusy(false) }
          }}><Trash2 size={14} />{t("确认删除")}</button>
        </div>
      </Modal>}
    </section>
  );
}
