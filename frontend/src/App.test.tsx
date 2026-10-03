import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
  fireEvent,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "./api";
import App from "./App";
import type { Batch, Task } from "./types";
vi.mock("./api", () => ({
  api: vi.fn(),
  upload: vi.fn(),
  watchBatch: () => () => {},
  imageUrl: async (path: string) => path,
}));
let batch: Batch, tasks: Task[];
beforeEach(() => {
  localStorage.clear();
  tasks = [];
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 1280,
  });
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  HTMLElement.prototype.scrollTo = vi.fn();
  batch = {
    id: "a".repeat(32),
    workspace_id: "a".repeat(32),
    project_name: "测试项目",
    folder: "20261003_测试项目",
    phase: "draft",
    created_at: "2026-10-03T12:00:00+08:00",
    updated_at: "one",
    archived: false,
    job_name: null,
    cloud_state: null,
    last_error: null,
    image_output_dir: null,
  };
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, method = "GET", body) => {
    if (path === "/config")
      return {
        project: "demo",
        bucket: "bucket",
        data_dir: "D:/data",
        model: "gemini-3.1-flash-image",
        credentials_configured: false,
      } as never;
    if (path === "/batches") return [{ ...batch }] as never;
    if (path === "/references") return [] as never;
    if (path.endsWith("/results"))
      return { tasks: [], counts: {}, final: false, row_errors: [] } as never;
    if (path.endsWith("/tasks") && method === "POST") {
      const task = {
        ...(body as object),
        id: "b".repeat(32),
        created_at: "2026-10-03T12:01:00+08:00",
      } as Task;
      tasks.push(task);
      batch.updated_at = "two";
      return task as never;
    }
    if (path.endsWith("/tasks")) return [...tasks] as never;
    throw new Error("Unexpected test request " + path);
  });
});
afterEach(cleanup);
it("右键归档隐藏项目，设置归档中确认后才删除", async () => {
  const user = userEvent.setup(), base = vi.mocked(api).getMockImplementation()!;
  let deleted = false;
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/batches" && deleted) return [] as never;
    if (path === `/workspaces/${batch.id}/archive`) {
      batch.archived = true; batch.updated_at = "archived";
      return [{ ...batch }] as never;
    }
    if (path === `/workspaces/${batch.id}` && method === "DELETE") {
      deleted = true; return { deleted: true } as never;
    }
    return base(path, method, body);
  });
  render(<App />);
  const title = await screen.findByRole("button", { name: "测试项目" });
  fireEvent.contextMenu(title, { clientX: 100, clientY: 200 });
  await user.click(screen.getByRole("menuitem", { name: "归档项目" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "测试项目" })).toBeNull());
  await user.click(screen.getByRole("button", { name: "设置" }));
  await user.click(screen.getByRole("button", { name: "归档" }));
  await user.click(screen.getByRole("button", { name: "删除归档项目 测试项目" }));
  expect(deleted).toBe(false);
  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(deleted).toBe(false);
  await user.click(screen.getByRole("button", { name: "删除归档项目 测试项目" }));
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await screen.findByText("暂无归档项目");
  expect(deleted).toBe(true);
});
it("运行中的项目不能从右键菜单归档", async () => {
  batch.phase = "monitoring";
  render(<App />);
  fireEvent.contextMenu(await screen.findByRole("button", { name: "测试项目" }));
  expect((screen.getByRole("menuitem", { name: "归档项目" }) as HTMLButtonElement).disabled).toBe(true);
});
it("没有云端凭证时不会显示已连接", async () => {
  render(<App />);
  expect(await screen.findByRole("button", { name: "Google Cloud：未配置" })).toBeTruthy();
  expect(screen.queryByText("已连接")).toBeNull();
});
it("后台凭证失败解除提交状态并允许取消本地批次", async () => {
  const user = userEvent.setup(), base = vi.mocked(api).getMockImplementation()!;
  tasks = [{ id: 'b'.repeat(32), name: '测试任务', prompt: 'draw', refs: [], temperature: null,
    aspect_ratio: '16:9', image_size: '1K', image_count: 1, generation_config: {} }];
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path.endsWith('/submit')) {
      batch.last_error = '未配置凭证'; batch.updated_at = 'submit-failed';
      return { queued: true } as never;
    }
    if (path.endsWith('/cancel')) {
      batch.phase = 'cancelled'; batch.last_error = null; batch.updated_at = 'cancelled';
      return { ...batch } as never;
    }
    return base(path, method, body);
  });
  render(<App />);
  await user.click(await screen.findByRole('button', { name: '提交批次' }));
  await screen.findByText('未配置凭证');
  expect(screen.queryByText('提交中')).toBeNull();
  expect(screen.queryByRole('button', { name: '刷新结果' })).toBeNull();
  await user.click(screen.getByRole('button', { name: '取消本轮' }));
  await waitFor(() => expect(batch.phase).toBe('cancelled'));
  expect(screen.getAllByText('已取消').length).toBeGreaterThan(0);
});
it("图库图片点击只预览，加号添加，图库排序拖入输入框不会添加", async () => {
  const user = userEvent.setup(),
    base = vi.mocked(api).getMockImplementation()!;
  const ref = {
    path: "references/characters/example.png",
    mime_type: "image/png",
    dimensions: [100, 100],
    size: 10,
    sha256: "hash",
  };
  vi.mocked(api).mockImplementation(async (path, method, body) =>
    path === "/references"
      ? ([ref] as never)
      : (base(path, method, body) as never),
  );
  render(<App />);
  await screen.findByRole("button", { name: "测试项目" });
  await user.click(screen.getByRole("button", { name: "人设" }));
  await user.click(
    await screen.findByRole("button", { name: "预览参考图 example.png" }),
  );
  expect(screen.getByRole("dialog", { name: "example.png" })).toBeTruthy();
  expect(document.querySelectorAll(".composer-ref")).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "关闭弹窗" }));
  const dataTransfer = {
    getData: (type: string) =>
      type === "application/x-vbs-library-sort" ? ref.path : "",
    types: ["application/x-vbs-library-sort"],
    files: [],
  };
  fireEvent.drop(document.querySelector(".composer")!, { dataTransfer });
  expect(document.querySelectorAll(".composer-ref")).toHaveLength(0);
  await user.click(
    screen.getByRole("button", { name: "加入参考图 example.png" }),
  );
  expect(document.querySelectorAll(".composer-ref")).toHaveLength(1);
});
it("保存的项目已不存在时选择有效项目，不显示内部编号", async () => {
  localStorage.setItem("vbs-workspace", "c".repeat(32));
  render(<App />);
  await screen.findByRole("button", { name: "当前项目：测试项目" });
  expect(
    screen.queryByRole("button", { name: "当前项目：" + "c".repeat(32) }),
  ).toBeNull();
});
it("侧栏收起后左下角保留展开入口", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText("测试项目", { selector: ".project-title span" });
  await user.click(screen.getByRole("button", { name: "收起侧栏" }));
  expect(screen.getByText("参考图库").closest("[hidden]")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "展开侧栏" }).closest(".sidebar-bottom"),
  ).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "展开侧栏" }));
  expect(screen.getByText("参考图库")).toBeTruthy();
});
it("窄窗口默认收起，仍能打开图库", async () => {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 560,
  });
  const user = userEvent.setup();
  render(<App />);
  expect(screen.getByText("参考图库").closest("[hidden]")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "展开侧栏" }));
  expect(screen.getByText("参考图库")).toBeTruthy();
  expect(screen.getByRole("button", { name: "关闭侧栏遮罩" })).toBeTruthy();
});
it("再次点击当前项目切换展开状态并保留正在写的提示词", async () => {
  const user = userEvent.setup();
  render(<App />);
  const project = await screen.findByRole("button", { name: "测试项目" });
  await user.type(
    screen.getByRole("textbox", { name: "提示词" }),
    "正在编辑的提示词",
  );
  expect(project.getAttribute("aria-expanded")).toBe("true");
  await user.click(project);
  expect(project.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("还没有任务")).toBeNull();
  expect(
    (screen.getByRole("textbox", { name: "提示词" }) as HTMLTextAreaElement)
      .value,
  ).toBe("正在编辑的提示词");
  await user.click(project);
  expect(project.getAttribute("aria-expanded")).toBe("true");
});
it("侧栏调宽支持任意中间宽度和完全收起恢复", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: "测试项目" });
  const separator = screen.getByRole("separator", { name: "调整侧栏宽度" });
  separator.focus();
  await user.keyboard("{ArrowLeft}{ArrowLeft}");
  expect(separator.getAttribute("aria-valuenow")).toBe("218");
  expect((separator.closest("aside") as HTMLElement).style.width).toBe("218px");
  await user.keyboard("{Home}");
  expect(separator.getAttribute("aria-valuenow")).toBe("0");
  await user.click(screen.getByRole("button", { name: "展开侧栏" }));
  expect(separator.getAttribute("aria-valuenow")).toBe("218");
});
it("拖动侧栏边缘连续改变宽度并保存任意中间值", async () => {
  Object.defineProperty(window, "PointerEvent", {
    configurable: true,
    value: MouseEvent,
  });
  HTMLElement.prototype.setPointerCapture = vi.fn();
  HTMLElement.prototype.releasePointerCapture = vi.fn();
  render(<App />);
  await screen.findByRole("button", { name: "测试项目" });
  const separator = screen.getByRole("separator", { name: "调整侧栏宽度" });
  fireEvent.pointerDown(separator, { clientX: 258 });
  fireEvent.pointerMove(separator, { clientX: 173 });
  expect(separator.getAttribute("aria-valuenow")).toBe("173");
  fireEvent.pointerUp(separator, { clientX: 173 });
  fireEvent.pointerDown(separator, { clientX: 173 });
  fireEvent.pointerMove(separator, { clientX: 24 });
  fireEvent.pointerUp(separator, { clientX: 24 });
  expect(screen.getByRole("button", { name: "展开侧栏" })).toBeTruthy();
});
it("关于只提供查看和检查连接，设置是独立窗口", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: "测试项目" });
  await user.click(screen.getByRole("button", { name: "关于" }));
  expect(screen.getByRole("dialog", { name: "关于" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "归档当前项目" })).toBeNull();
  expect(screen.getByRole("button", { name: "检查连接" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "关闭弹窗" }));
  await user.click(screen.getByRole("button", { name: "设置" }));
  expect(screen.getByRole("switch", { name: "深色主题" })).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Google Cloud 登录" }),
  ).toBeTruthy();
});
it("三张图片仍只发一个原文任务，切换数量不会修改旧任务", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText("测试项目", { selector: ".project-title span" });
  await user.click(screen.getByRole("button", { name: "图片数量：1" }));
  await user.click(screen.getByRole("option", { name: "3" }));
  await user.type(
    screen.getByRole("textbox", { name: "提示词" }),
    "原始提示词",
  );
  await user.click(screen.getByRole("button", { name: "加入任务" }));
  await waitFor(() => expect(tasks).toHaveLength(1));
  expect(tasks[0].prompt).toBe("原始提示词");
  expect(tasks[0].image_count).toBe(3);
  expect(
    vi.mocked(api).mock.calls.filter(([, method]) => method === "POST"),
  ).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "图片数量：3" }));
  await user.click(screen.getByRole("option", { name: "4" }));
  expect(tasks[0].image_count).toBe(3);
});

it("项目右键重命名保留目录，取消不会保存", async () => {
  const user = userEvent.setup(), base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === `/workspaces/${batch.id}` && method === "PUT") {
      batch.project_name = (body as { project_name: string }).project_name;
      batch.updated_at = "renamed";
      return [{ ...batch }] as never;
    }
    return base(path, method, body);
  });
  render(<App />);
  fireEvent.contextMenu(await screen.findByRole("button", { name: "测试项目" }));
  await user.click(screen.getByRole("menuitem", { name: "重命名项目" }));
  const name = screen.getByRole("textbox", { name: "项目名称" });
  expect((name as HTMLInputElement).value).toBe("测试项目");
  await user.clear(name);
  await user.type(name, "修改后的项目");
  await user.click(screen.getByRole("button", { name: "保存名称" }));
  await screen.findByRole("button", { name: "修改后的项目" });
  expect(batch.folder).toBe("20261003_测试项目");
  fireEvent.contextMenu(screen.getByRole("button", { name: "修改后的项目" }));
  await user.click(screen.getByRole("menuitem", { name: "重命名项目" }));
  await user.type(screen.getByRole("textbox", { name: "项目名称" }), "未保存");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(batch.project_name).toBe("修改后的项目");
});

it("打开输出目录按钮打开当前批次而非进入设置", async () => {
  const user = userEvent.setup();
  const openOutput = vi.fn().mockResolvedValue(undefined);
  window.studio = { openOutput } as never;
  try {
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "打开输出目录" }));
    expect(openOutput).toHaveBeenCalledWith(batch.id);
    expect(screen.queryByRole("dialog")).toBeNull();
  } finally { delete window.studio; }
});
