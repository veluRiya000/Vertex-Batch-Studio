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
function Fixture() {
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
