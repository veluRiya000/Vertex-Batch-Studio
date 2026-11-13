/* 界面摘录说明：参考图库的窗格/列表、点击预览、加号添加、拖动排序和删除。可改缩略图排版；保留预览/添加/排序/删除的各自事件和拖动数据。
 * 仅此副本新增说明；原工程未改动。 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  GripVertical,
  FolderOpen,
  ImagePlus,
  Images,
  LayoutGrid,
  List,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { Media, Modal } from "./components";
import { useTranslation } from "./i18n";
import type { Reference, ReferenceFolder } from "./types";

// 界面组件 ReferenceLibrary：参考图库的窗格/列表、点击预览、加号添加、拖动排序和删除。
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
  categories = [{ id: "styles", label: "风格" }, { id: "characters", label: "人设" }, { id: "scenes", label: "场景" }],
  addCategory,
  chooseFolder,
  deleteCategory,
  moveCategory,
  categoryCounts,
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
  categories?: { id: string; label: string }[];
  addCategory?: (label: string, folder?: ReferenceFolder, progress?: (completed: number) => void) => Promise<void>;
  chooseFolder?: () => Promise<ReferenceFolder | null>;
  deleteCategory?: (id: string) => Promise<void>;
  moveCategory?: (ref: Reference, destination: string) => Promise<void>;
  categoryCounts?: Record<string, number>;
}) {
  const t = useTranslation();
  const browser = useRef<HTMLDivElement>(null);
  const [compact, setCompact] = useState(false);
  const [categoryDialog, setCategoryDialog] = useState<"add" | string>();
  const [categoryName, setCategoryName] = useState("");
  const [categoryBusy, setCategoryBusy] = useState(false);
  const [categoryError, setCategoryError] = useState("");
  const [folder, setFolder] = useState<ReferenceFolder>();
  const [folderPicking, setFolderPicking] = useState(false);
  const [importedCount, setImportedCount] = useState(0);
  const folderSelection = useRef(0);
  function openAddCategory() {
    folderSelection.current++;
    setFolder(undefined); setFolderPicking(false); setImportedCount(0);
    setCategoryName(""); setCategoryError(""); setCategoryDialog("add");
  }
  function closeCategoryDialog() {
    if (categoryBusy) return;
    folderSelection.current++;
    setFolder(undefined); setFolderPicking(false); setCategoryDialog(undefined);
  }
  async function selectFolder() {
    if (!chooseFolder || folderPicking || categoryBusy) return;
    const selection = ++folderSelection.current;
    setFolderPicking(true); setCategoryError("");
    try {
      const value = await chooseFolder();
      if (selection === folderSelection.current && value) {
        setFolder(value); setCategoryName(value.label);
      }
    } catch (e) {
      if (selection === folderSelection.current)
        setCategoryError(e instanceof Error ? e.message : t("无法读取文件夹"));
    } finally {
      if (selection === folderSelection.current) setFolderPicking(false);
    }
  }
  const [referenceMenu, setReferenceMenu] = useState<{ ref: Reference; x: number; y: number }>();
  const [movingCategory, setMovingCategory] = useState(false);
  const [categoryMenu, setCategoryMenu] = useState<{ id: string; x: number; y: number }>();
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!categoryMenu && !referenceMenu) return;
    menu.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)) { setCategoryMenu(undefined); setReferenceMenu(undefined); }
    };
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setCategoryMenu(undefined); setReferenceMenu(undefined); }
    };
    const scroll = (event: Event) => {
      if (event.target instanceof Node && menu.current?.contains(event.target)) return;
      setCategoryMenu(undefined); setReferenceMenu(undefined);
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", keyboard);
    window.addEventListener("resize", scroll);
    window.addEventListener("scroll", scroll, true);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", keyboard);
      window.removeEventListener("resize", scroll);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [categoryMenu, referenceMenu]);
  useLayoutEffect(() => {
    if (!browser.current || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const node = browser.current!;
      setCompact(node.clientHeight < 125 || node.clientWidth < 165);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(browser.current);
    measure();
    return () => observer.disconnect();
  }, []);
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
  const closingCount = categoryDialog ? (categoryCounts?.[categoryDialog] ?? (categoryDialog === category ? references.length : undefined)) : undefined;
  const closingLabel = categories.find(item => item.id === categoryDialog)?.label || "";
  function openReferenceMenu(ref: Reference, x: number, y: number) {
    if (!moveCategory || busy || saving || movingCategory) return;
    setCategoryMenu(undefined); setReferenceMenu({ ref, x, y });
  }
  function chooseImport() {
    if (category === "uncategorized") return;
    if (!categories.length && addCategory) {
      openAddCategory();
    } else chooseFiles();
  }
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
        </div>
      </div>
      <div className="category-tabs">
        {categories.map(({ id, label }) => (
          <span className={"category-tab " + (category === id ? "active" : "")} key={id}>
          <button
            className={category === id ? "active" : ""}
            title={deleteCategory && id !== "uncategorized" ? t("右键删除分类") : undefined}
            aria-haspopup={deleteCategory && id !== "uncategorized" ? "menu" : undefined}
            onContextMenu={event => {
              if (id === "uncategorized") { event.preventDefault(); return; }
              if (!deleteCategory) return;
              event.preventDefault();
              setReferenceMenu(undefined);
              if (!saving && !busy) setCategoryMenu({ id, x: event.clientX, y: event.clientY });
            }}
            onKeyDown={event => {
              if (id === "uncategorized" && (event.key === "ContextMenu" || event.shiftKey && event.key === "F10")) {
                event.preventDefault(); return;
              }
              if (deleteCategory && id !== "uncategorized" && !saving && !busy &&
                  (event.key === "ContextMenu" || event.shiftKey && event.key === "F10")) {
                event.preventDefault();
                const box = event.currentTarget.getBoundingClientRect();
                setReferenceMenu(undefined);
                setCategoryMenu({ id, x: box.left, y: box.bottom });
              }
            }}
            onClick={() => {
              setCategoryMenu(undefined);
              setReferenceMenu(undefined);
              if (!saving) {
                clearDrag();
                setCategory(id);
              }
            }}
            disabled={saving}
          >
            {t(label)}
          </button>
          </span>
        ))}
        {addCategory && <button className="category-create" aria-label={t("添加参考图分类")} title={t("添加参考图分类")}
          disabled={saving || busy} onClick={openAddCategory}><Plus size={15} /></button>}
      </div>
      <div
        ref={browser}
        className={"reference-grid reference-browser " + mode + "-mode" + (compact ? " compact-refs" : "")}
        aria-busy={saving}
        onDragOver={(event) => {
          event.preventDefault();
          if (category === "uncategorized" && !source.current) event.dataTransfer.dropEffect = "none";
        }}
        onDrop={(event) => {
          event.preventDefault();
          if (event.dataTransfer.files.length) {
            event.stopPropagation();
            if (category === "uncategorized") { clearDrag(); return; }
            if (!categories.length) chooseImport();
            else importFiles(Array.from(event.dataTransfer.files));
          }
          else if (source.current && items.length)
            void move(source.current, items.at(-1)!.path);
          clearDrag();
        }}
      >
        {items.map((ref, index) => (
          <div
            key={ref.path}
            onContextMenu={event => {
              if (!moveCategory) return;
              event.preventDefault(); openReferenceMenu(ref, event.clientX, event.clientY);
            }}
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
              event.dataTransfer.effectAllowed = "copyMove";
              event.dataTransfer.setData("application/x-vbs-reference", JSON.stringify(ref));
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
                if (event.key === "ContextMenu" || event.shiftKey && event.key === "F10") {
                  if (moveCategory) {
                    event.preventDefault();
                    const box = event.currentTarget.getBoundingClientRect();
                    openReferenceMenu(ref, box.left, box.bottom);
                  }
                  return;
                }
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
              <span className="reference-photo"><Media
                path={
                  "/references/file?" + new URLSearchParams({ path: ref.path })
                }
                alt={name(ref)}
              /></span>
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
        {!items.length && category !== "uncategorized" && (
          <button
            className="library-empty"
            aria-label={t("导入参考图")}
            onClick={chooseImport}
          >
            <ImagePlus size={22} aria-hidden />
            <span aria-hidden="true">{t("导入参考图")}</span>
          </button>
        )}
        {!!items.length && category !== "uncategorized" && <button className="library-import-more" aria-label={t("导入参考图")} title={t("导入参考图")}
          disabled={busy} onClick={chooseImport}><ImagePlus size={17} /><span>{t("导入参考图")}</span></button>}
      </div>
      {categoryMenu && createPortal(<div ref={menu} className="project-context-menu category-context-menu" role="menu" aria-label={t("参考图分类操作")}
        style={{ left: Math.max(8, Math.min(categoryMenu.x, window.innerWidth - 198)), top: Math.max(8, Math.min(categoryMenu.y, window.innerHeight - 65)) }}>
        <button role="menuitem" disabled={busy || saving} onClick={() => {
          setCategoryDialog(categoryMenu.id); setCategoryError(""); setCategoryMenu(undefined);
        }}><Trash2 size={14} />{t("删除分类")}</button>
      </div>, document.body)}
      {referenceMenu && createPortal(<div ref={menu} className="project-context-menu reference-move-menu" role="menu" aria-label={t("移至分类")}
        style={{ left: Math.max(8, Math.min(referenceMenu.x, window.innerWidth - 210)), top: Math.max(8, Math.min(referenceMenu.y, window.innerHeight - 328)), maxHeight: "min(320px, calc(100vh - 24px))", overflowY: "auto" }}>
        <span className="reference-menu-label">{t("移至分类")}</span>
        {categories.filter(item => item.id !== (referenceMenu.ref.category_id || category)).map(item =>
          <button key={item.id} role="menuitem" disabled={movingCategory || busy || saving} onClick={async () => {
            if (!moveCategory || movingCategory) return;
            setMovingCategory(true);
            try { await moveCategory(referenceMenu.ref, item.id); setReferenceMenu(undefined); }
            catch (e) { error(e instanceof Error ? e.message : t("操作未完成")); }
            finally { setMovingCategory(false); }
          }}>{t(item.label)}</button>)}
        {categories.length < 2 && <span className="reference-menu-label">{t("请先添加其他分类")}</span>}
      </div>, document.body)}
      {categoryDialog && <Modal title={t(categoryDialog === "add" ? "添加参考图分类" : "删除分类")}
        close={closeCategoryDialog}>
        <form onSubmit={async event => {
          event.preventDefault(); if (categoryBusy || folderPicking) return;
          setCategoryBusy(true); setCategoryError("");
          try {
            if (categoryDialog === "add") await addCategory?.(categoryName, folder, setImportedCount);
            else await deleteCategory?.(categoryDialog);
            setCategoryDialog(undefined);
          } catch (e) { setCategoryError(e instanceof Error ? e.message : t("操作未完成")); }
          finally { setCategoryBusy(false); }
        }}>
          {categoryDialog === "add" ? <>
            <label className="form-label">{t("分类名称")}<input autoFocus maxLength={30} value={categoryName}
              disabled={categoryBusy} onChange={event => setCategoryName(event.target.value)} /></label>
            {chooseFolder && <div className="reference-folder-import">
              <button type="button" className="secondary-button" disabled={categoryBusy || folderPicking}
                onClick={() => void selectFolder()}><FolderOpen size={15} />{t(folderPicking ? "正在读取文件夹" : "导入文件夹")}</button>
              {folder && <div className="reference-folder-selection">
                <span title={folder.source}>{folder.source}</span>
                <button type="button" className="icon-button" aria-label={t("移除所选文件夹")} disabled={categoryBusy}
                  onClick={() => { folderSelection.current++; setFolder(undefined); }}><X size={14} /></button>
                <small>{folder.files.length} {t("张图片")} · {t("仅当前文件夹")}</small>
              </div>}
              {categoryBusy && folder && <p className="reference-import-progress" role="status">
                {t("正在导入")} {importedCount} / {folder.files.length}
              </p>}
            </div>}
          </>
            : <p>{closingCount === 0
              ? t("删除空分类") + `「${closingLabel}」？`
              : closingCount !== undefined
                ? `「${closingLabel}」${t("中的")} ${closingCount} ${t("张参考图会归入“未分类”，图片不会删除。")}`
                : t("删除此分类？图片文件和任务引用会保留。")}</p>}
          {categoryError && <p className="settings-error" role="alert">{categoryError}</p>}
          <div className="archive-confirm-actions"><button className="secondary-button" type="button" disabled={categoryBusy}
            onClick={closeCategoryDialog}>{t("取消")}</button>
            <button className="primary-button" disabled={categoryBusy || folderPicking || categoryDialog === "add" && (!categoryName.trim() || !!folder && !folder.files.length)}>{t(categoryDialog === "add" ? "添加" : "确认删除")}</button></div>
        </form>
      </Modal>}
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
