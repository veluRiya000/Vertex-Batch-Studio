import { useState } from "react";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReferenceLibrary } from "./ReferenceLibrary";
import type { Reference } from "./types";
vi.mock("./api", () => ({ imageUrl: async (path: string) => path }));
const refs = ["a", "b", "c"].map((name) => ({
  path: `references/characters/${name}.png`,
  mime_type: "image/png",
  dimensions: [100, 100],
  size: 100,
  sha256: name,
})) as Reference[];
const preview = vi.fn(),
  remove = vi.fn(),
  add = vi.fn(),
  reorder = vi.fn(),
  error = vi.fn();
function Fixture({ closeCategory, counts }: { closeCategory?: (id: string) => Promise<void>; counts?: Record<string,number> } = {}) {
  const [items, setItems] = useState(refs);
  return (
    <ReferenceLibrary
      references={items}
      category="characters"
      setCategory={() => {}}
      importFiles={() => {}}
      chooseFiles={() => {}}
      add={add}
      remove={async (ref) => { await remove(ref); setItems((old) => old.filter((item) => item.path !== ref.path)); }}
      preview={preview}
      error={error}
      busy={false}
      deleteCategory={closeCategory}
      categoryCounts={counts}
      reorder={async (paths) => {
        await reorder(paths);
        setItems(paths.map((path) => refs.find((ref) => ref.path === path)!));
      }}
    />
  );
}
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  reorder.mockResolvedValue(undefined);
  remove.mockResolvedValue(undefined);
});
afterEach(cleanup);
it("两种模式都有删除按钮，取消不删除，错误保留图片，确认成功后移除", async () => {
  const user = userEvent.setup();
  render(<Fixture />);
  await user.click(screen.getByRole("button", { name: "删除参考图 a.png" }));
  expect(remove).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "列表模式" }));
  await user.click(screen.getByRole("button", { name: "删除参考图 a.png" }));
  remove.mockRejectedValueOnce(new Error("此图片正在使用"));
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "预览参考图 a.png" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "预览参考图 a.png" })).toBeNull());
  expect(add).not.toHaveBeenCalled();
  expect(preview).not.toHaveBeenCalled();
});
it("两种模式中点击条目只预览，独立加号才加入对话", async () => {
  const user = userEvent.setup();
  render(<Fixture />);
  await user.click(screen.getByRole("button", { name: "预览参考图 a.png" }));
  expect(preview).toHaveBeenLastCalledWith(refs, 0);
  expect(add).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "加入参考图 a.png" }));
  expect(add).toHaveBeenLastCalledWith(refs[0]);
  expect(preview).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "列表模式" }));
  expect(
    screen
      .getByRole("button", { name: "列表模式" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  await user.click(screen.getByRole("button", { name: "预览参考图 b.png" }));
  expect(preview).toHaveBeenLastCalledWith(refs, 1);
  expect(add).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem("vbs-reference-view")).toBe("list");
});
it("窗格和列表拖动排序会保存完整顺序，拖动本身不加入任务或预览", async () => {
  const user = userEvent.setup();
  render(<Fixture />);
  async function drag(from: string, to: string) {
    const source = screen
      .getByRole("button", { name: `预览参考图 ${from}.png` })
      .closest(".reference-card")!;
    const target = screen
      .getByRole("button", { name: `预览参考图 ${to}.png` })
      .closest(".reference-card")!;
    const dataTransfer = {
      setData: vi.fn(),
      files: [],
      effectAllowed: "",
      dropEffect: "",
    };
    fireEvent.dragStart(source, { dataTransfer });
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    fireEvent.dragEnd(source, { dataTransfer });
    await waitFor(() =>
      expect(
        document.querySelector(".reference-browser")!.getAttribute("aria-busy"),
      ).toBe("false"),
    );
  }
  await drag("b", "a");
  expect(reorder).toHaveBeenLastCalledWith([
    refs[1].path,
    refs[0].path,
    refs[2].path,
  ]);
  expect(
    screen
      .getAllByRole("button", { name: /预览参考图/ })
      .map((button) => button.textContent),
  ).toEqual(["b.png", "a.png", "c.png"]);
  await user.click(screen.getByRole("button", { name: "列表模式" }));
  await drag("c", "b");
  expect(reorder).toHaveBeenLastCalledWith([
    refs[2].path,
    refs[1].path,
    refs[0].path,
  ]);
  expect(add).not.toHaveBeenCalled();
  expect(preview).not.toHaveBeenCalled();
});
it("排序保存失败恢复原顺序并显示错误", async () => {
  reorder.mockRejectedValue(new Error("save failed"));
  const user = userEvent.setup();
  render(<Fixture />);
  await user.click(screen.getByRole("button", { name: "预览参考图 a.png" }));
  await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
  await waitFor(() => expect(error).toHaveBeenCalledWith("save failed"));
  expect(
    screen
      .getAllByRole("button", { name: /预览参考图/ })
      .map((button) => button.textContent),
  ).toEqual(["a.png", "b.png", "c.png"]);
});

it("分类没有关闭叉，右键或菜单键删除分类，取消保留分类", async () => {
  const closeCategory = vi.fn().mockResolvedValue(undefined), user = userEvent.setup();
  render(<Fixture closeCategory={closeCategory} />);
  expect(document.querySelector('.category-remove')).toBeNull();
  const tab = screen.getByRole('button', { name: '风格' });
  await user.click(tab);
  expect(screen.queryByRole('menu')).toBeNull();
  expect(closeCategory).not.toHaveBeenCalled();
  fireEvent.contextMenu(tab, { clientX: 100, clientY: 100 });
  await user.click(screen.getByRole('menuitem', { name: '删除分类' }));
  await user.click(screen.getByRole('button', { name: '取消' }));
  expect(closeCategory).not.toHaveBeenCalled();
  fireEvent.keyDown(tab, { key: 'F10', shiftKey: true });
  await user.click(screen.getByRole('menuitem', { name: '删除分类' }));
  await user.click(screen.getByRole('button', { name: '确认删除' }));
  await waitFor(() => expect(closeCategory).toHaveBeenCalledWith('styles'));
});

it("删除空分类不再误导有图片迁入未分类，有图时显示实际数量", async () => {
  const user=userEvent.setup();
  render(<Fixture closeCategory={vi.fn()} counts={{styles:0,characters:3}} />);
  fireEvent.contextMenu(screen.getByRole('button',{name:'风格'}));
  await user.click(screen.getByRole('menuitem',{name:'删除分类'}));
  expect(screen.getByText('删除空分类「风格」？')).toBeTruthy();
  expect(screen.queryByText(/归入/)).toBeNull();
  await user.click(screen.getByRole('button',{name:'取消'}));
  fireEvent.contextMenu(screen.getByRole('button',{name:'人设'}));
  await user.click(screen.getByRole('menuitem',{name:'删除分类'}));
  expect(screen.getByText(/3 张参考图会归入/)).toBeTruthy();
});

it("未分类不提供右键或菜单键删除，也不会出现删除弹窗", async () => {
  const close=vi.fn().mockResolvedValue(undefined);
  render(<ReferenceLibrary references={refs} category="uncategorized" setCategory={()=>{}}
    categories={[{id:'styles',label:'风格'},{id:'uncategorized',label:'未分类'}]}
    categoryCounts={{uncategorized:3}} deleteCategory={close} importFiles={()=>{}} chooseFiles={()=>{}}
    add={add} preview={preview} reorder={reorder} error={error} busy={false} />);
  fireEvent.contextMenu(screen.getByRole('button',{name:'未分类'}));
  expect(screen.queryByRole('menu')).toBeNull();
  fireEvent.keyDown(screen.getByRole('button',{name:'未分类'}),{key:'F10',shiftKey:true});
  expect(screen.queryByRole('menu')).toBeNull();
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('button',{name:'未分类'}).hasAttribute('title')).toBe(false);
  expect(close).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});

it("列表与窗格均可用右键移动分类，失败保留菜单和图片", async () => {
  const transfer=vi.fn().mockRejectedValueOnce(new Error('move failed')).mockResolvedValue(undefined),user=userEvent.setup();
  render(<ReferenceLibrary references={refs} category="characters" setCategory={()=>{}}
    moveCategory={transfer} importFiles={()=>{}} chooseFiles={()=>{}}
    add={add} preview={preview} reorder={reorder} error={error} busy={false} />);
  fireEvent.contextMenu(screen.getByRole('button',{name:'预览参考图 a.png'}));
  await user.click(screen.getByRole('menuitem',{name:'风格'}));
  await waitFor(()=>expect(error).toHaveBeenCalledWith('move failed'));
  expect(screen.getByRole('menu',{name:'移至分类'})).toBeTruthy();
  await user.click(screen.getByRole('menuitem',{name:'风格'}));
  await waitFor(()=>expect(screen.queryByRole('menu')).toBeNull());
  await user.click(screen.getByRole('button',{name:'列表模式'}));
  fireEvent.keyDown(screen.getByRole('button',{name:'预览参考图 b.png'}),{key:'F10',shiftKey:true});
  await user.click(screen.getByRole('menuitem',{name:'场景'}));
  await waitFor(()=>expect(transfer).toHaveBeenLastCalledWith(refs[1],'scenes'));
  expect(add).not.toHaveBeenCalled();expect(preview).not.toHaveBeenCalled();
});

it("未分类两种视图均无导入按钮，拖入新文件不导入，已有图片仍可预览", async () => {
  const imported=vi.fn(),choose=vi.fn(),user=userEvent.setup();
  render(<ReferenceLibrary references={refs} category="uncategorized" setCategory={()=>{}}
    importFiles={imported} chooseFiles={choose} add={add} remove={remove}
    preview={preview} reorder={reorder} error={error} busy={false} />);
  for (const mode of ['窗格模式','列表模式']) {
    await user.click(screen.getByRole('button',{name:mode}));
    expect(screen.queryByRole('button',{name:'导入参考图'})).toBeNull();
    fireEvent.drop(document.querySelector('.reference-browser')!,{dataTransfer:{files:[new File(['image'],'new.png',{type:'image/png'})]}});
  }
  expect(imported).not.toHaveBeenCalled();expect(choose).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'预览参考图 a.png'}));
  expect(preview).toHaveBeenCalledWith(refs,0);
  expect(screen.getByRole('button',{name:'删除参考图 a.png'})).toBeTruthy();
});
