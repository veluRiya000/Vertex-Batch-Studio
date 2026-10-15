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
    if (path === "/models/refresh") return {
      project: "demo", bucket: "bucket", data_dir: "D:/data",
      model: "gemini-3.1-flash-image", credentials_configured: false,
    } as never;
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
it("2.1 禁用温度，新任务不保存温度，切回原模型恢复温度选择", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  const normal = "gemini-3.1-flash-image", nano = "gemini-nano-banana-2.1";
  let chosen = normal;
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/models/selection") chosen = (body as { model: string }).model;
    if (["/config", "/models/refresh", "/models/selection"].includes(path)) return {
      project: "demo", bucket: "bucket", data_dir: "D:/data", model: chosen,
      unsupported_generation_parameters: chosen === nano ? ["temperature", "topP", "topK", "seed", "logprobs"] : [],
      model_catalog: { models: [
        { id: normal, label: "Nano Banana 2" }, { id: nano, label: "Nano Banana 2.1" },
      ], source: "official", refreshing: false, fetched_at: null, message: null },
    } as never;
    return base(path, method, body);
  });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText("测试项目", { selector: ".project-title span" });
  await user.click(screen.getByRole("button", { name: "温度：默认" }));
  await user.click(screen.getByRole("option", { name: "1.5" }));
  await user.click(screen.getByRole("button", { name: "模型：Nano Banana 2" }));
  await user.click(screen.getByRole("option", { name: "Nano Banana 2.1" }));
  const temperature = await screen.findByRole("button", { name: "温度：不支持" });
  expect((temperature as HTMLButtonElement).disabled).toBe(true);
  expect(temperature.title).toContain("提交时不会发送");
  await user.click(temperature);
  expect(screen.queryByRole("listbox", { name: "温度选项" })).toBeNull();
  await user.type(screen.getByRole("textbox", { name: "提示词" }), "2.1 test");
  await user.click(screen.getByRole("button", { name: "加入任务" }));
  await waitFor(() => expect(tasks).toHaveLength(1));
  expect(tasks[0].temperature).toBeNull();
  await user.click(screen.getByRole("button", { name: "模型：Nano Banana 2.1" }));
  await user.click(screen.getByRole("option", { name: "Nano Banana 2" }));
  const restored = await screen.findByRole("button", { name: "温度：1.5" });
  expect((restored as HTMLButtonElement).disabled).toBe(false);
  expect(tasks[0].temperature).toBeNull();
});
it("2.1 的断网回退仍然禁用温度，不依赖新版本目录缓存", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (["/config", "/models/refresh"].includes(path)) return {
      model: "gemini-nano-banana-2.1", unsupported_generation_parameters: ["temperature"],
      model_catalog: { models: [], source: "unavailable", refreshing: false, fetched_at: null, message: "offline" },
    } as never;
    return base(path, method, body);
  });
  render(<App />);
  const button = await screen.findByRole("button", { name: "温度：不支持" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
});
it("官方动态模型可以切换，移除后的当前模型不会重新混入选项", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  const model = (id: string, label: string) => ({ id, label, regions: ["global"], source_url: "https://docs.cloud.google.com/example?hl=en", supports_image_size: true, aspect_ratios: ["16:9"], max_references: 14, batch_image_sizes: ["1K"] });
  let selected = "gemini-retired-image";
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/models/selection") selected = (body as { model: string }).model;
    if (["/config", "/models/refresh", "/models/selection"].includes(path)) return {
      project: "demo", bucket: "bucket", data_dir: "D:/data", model: selected,
      model_catalog: { models: [model("gemini-future-image", "未来生图模型")], source: "official", refreshing: false, fetched_at: null, message: null },
    } as never;
    return base(path, method, body);
  });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText("请选择可用模型");
  await user.click(screen.getByRole("button", { name: /^模型：/ }));
  expect(screen.queryByRole("option", { name: "gemini-retired-image" })).toBeNull();
  await user.click(screen.getByRole("option", { name: "未来生图模型" }));
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/models/selection", "POST", { model: "gemini-future-image" }));
  await waitFor(() => expect(screen.queryByText("请选择可用模型")).toBeNull());
});
it("断网缓存状态可见，切换失败保留当前模型", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/models/selection") throw new Error("切换失败");
    if (["/config", "/models/refresh"].includes(path)) return {
      model: "gemini-old-image", model_catalog: { models: [{ id: "gemini-new-image", label: "新增模型" }], source: "cache", refreshing: false, fetched_at: null, message: "断网，使用缓存" },
    } as never;
    return base(path, method, body);
  });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText("模型缓存");
  await user.click(screen.getByRole("button", { name: /^模型：/ }));
  await user.click(screen.getByRole("option", { name: "新增模型" }));
  await screen.findByText("切换失败");
  expect(screen.getByRole("button", { name: /^模型：/ }).textContent).toContain("gemini-old-image");
});
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
    vi.mocked(api).mock.calls.filter(([path, method]) => method === "POST" && path.endsWith("/tasks")),
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

it("队列卡片的时间和状态位于同一行，长名称保留完整悬停提示", async () => {
  tasks = [{ id: 'b'.repeat(32), name: '一个用于验证单行省略的非常长的任务名称', prompt: 'draw', refs: [], temperature: null,
    aspect_ratio: '16:9', image_size: '1K', image_count: 1, generation_config: {}, created_at: '2026-10-03T12:01:00+08:00' }];
  render(<App />);
  await screen.findByRole('button', { name: '测试项目' });
  await waitFor(() => expect(document.querySelector('.queue-meta')).toBeTruthy());
  const card = document.querySelector('.queue-item')!;
  expect(card.querySelector('strong')?.getAttribute('title')).toBe(tasks[0].name);
  const metadata = card.querySelector('.queue-meta')!;
  expect(metadata.querySelector('small')?.textContent).toContain('12:01');
  expect(metadata.querySelector('.queue-state')?.textContent).toBe('待提交');
});


it("队列跨过窄窗口阈值时立即切换布局，收起后恢复工作区", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: "测试项目" });
  const shell = document.querySelector(".studio-shell") as HTMLElement;
  expect(shell.style.gridTemplateColumns).toBe("258px minmax(0,1fr) 218px");
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 980 });
  fireEvent(window, new Event("resize"));
  expect(shell.style.gridTemplateColumns).toBe("258px minmax(0,1fr)");
  const queue = screen.getByRole("complementary", { name: "生成队列" });
  expect(screen.getByRole("button", { name: "收起生成队列" }).closest("aside")).toBe(queue);
  await user.click(screen.getByRole("button", { name: "收起生成队列" }));
  expect(screen.queryByRole("complementary", { name: "生成队列" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "展开生成队列" }));
  expect(screen.getByRole("complementary", { name: "生成队列" })).toBeTruthy();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1100 });
  fireEvent(window, new Event("resize"));
  expect(shell.style.gridTemplateColumns).toBe("258px minmax(0,1fr) 218px");
  expect(screen.getByRole("button", { name: "收起生成队列" }).closest("main")).toBeTruthy();
});

it("窄窗口打开队列后可从队列内部关闭", async () => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 900 });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: "测试项目" });
  expect(screen.queryByRole("complementary", { name: "生成队列" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "展开生成队列" }));
  expect(screen.getByRole("button", { name: "收起生成队列" }).closest(".queue")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "收起生成队列" }));
  expect(screen.getByRole("button", { name: "展开生成队列" })).toBeTruthy();
});


it('Harness Cloud entry and shell palette follow mode, closing returns to the same mode',async()=>{
  const user=userEvent.setup();
  render(<App/>);
  await screen.findByRole('button',{name:'测试项目'});
  expect(document.documentElement.dataset.studioMode).toBe('images');
  await user.click(screen.getByRole('button',{name:'Harness'}));
  expect(document.documentElement.dataset.studioMode).toBe('harness');
  fireEvent(window,new Event('vbs:open-cloud-settings'));
  await screen.findByRole('textbox',{name:'项目 ID'});
  expect(screen.queryByRole('switch',{name:'深色主题'})).toBeNull();
  await user.click(screen.getByRole('button',{name:'关闭弹窗'}));
  expect(document.documentElement.dataset.studioMode).toBe('harness');
  await user.click(document.querySelector('.top-actions button') as HTMLButtonElement);
  expect(screen.getByRole('switch',{name:'深色主题'})).toBeTruthy();
  await user.click(screen.getByRole('button',{name:'关闭弹窗'}));
  await user.click(screen.getByRole('button',{name:'生图'}));
  expect(document.documentElement.dataset.studioMode).toBe('images');
  expect(screen.getByRole('textbox',{name:'提示词'})).toBeTruthy();
});

it("未建项目时输入的提示词与参考图在创建项目后保留，只有点击加入任务才保存", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  let created = false;
  const reference = {path:"references/styles/character.png",mime_type:"image/png",dimensions:[800,600],size:100,sha256:"0".repeat(64)};
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if(path === "/batches") {
      if(method === "POST") {created=true;return {...batch} as never;}
      return (created ? [{...batch}] : []) as never;
    }
    if(path === "/references") return [reference] as never;
    return base(path,method,body);
  });
  const user=userEvent.setup();render(<App />);
  await screen.findByRole("button",{name:"加入参考图 character.png"});
  const prompt="  先写好的画面描述\n第二行也需要保留。  ";
  fireEvent.change(screen.getByRole("textbox",{name:"提示词"}),{target:{value:prompt}});
  await user.click(screen.getByRole("button",{name:"加入参考图 character.png"}));
  expect((screen.getByRole("button",{name:"加入任务"}) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getAllByRole("button",{name:"新建项目"})[0]);
  fireEvent.change(screen.getByRole("textbox",{name:"项目名称"}),{target:{value:"测试项目"}});
  await user.click(screen.getByRole("button",{name:"创建项目"}));
  await waitFor(()=>expect(screen.queryByRole("dialog",{name:"新建项目"})).toBeNull());
  expect((screen.getByRole("textbox",{name:"提示词"}) as HTMLTextAreaElement).value).toBe(prompt);
  expect(tasks).toHaveLength(0);
  expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith("/submit"))).toBe(false);
  await user.click(screen.getByRole("button",{name:"加入任务"}));
  await waitFor(()=>expect(tasks).toHaveLength(1));
  expect(tasks[0].prompt).toBe(prompt);
  expect(tasks[0].refs).toEqual([reference.path]);
  expect((screen.getByRole("textbox",{name:"提示词"}) as HTMLTextAreaElement).value).toBe("");
});

it("已有项目的新建操作仍然清空原项目的未发送提示词", async () => {
  const base=vi.mocked(api).getMockImplementation()!;
  const next={...batch,id:"c".repeat(32),workspace_id:"c".repeat(32),project_name:"第二个项目"};
  let created=false;
  vi.mocked(api).mockImplementation(async(path,method,body)=>{
    if(path==="/batches"){
      if(method==="POST"){created=true;return {...next} as never;}
      return (created?[{...batch},{...next}]:[{...batch}]) as never;
    }
    return base(path,method,body);
  });
  const user=userEvent.setup();render(<App />);
  await screen.findByText("测试项目",{selector:".project-title span"});
  fireEvent.change(screen.getByRole("textbox",{name:"提示词"}),{target:{value:"只属于原项目的草稿"}});
  await user.click(screen.getAllByRole("button",{name:"新建项目"})[0]);
  fireEvent.change(screen.getByRole("textbox",{name:"项目名称"}),{target:{value:next.project_name}});
  await user.click(screen.getByRole("button",{name:"创建项目"}));
  await waitFor(()=>expect(screen.queryByRole("dialog",{name:"新建项目"})).toBeNull());
  expect((screen.getByRole("textbox",{name:"提示词"}) as HTMLTextAreaElement).value).toBe("");
});

it("四次生图结果仍显示一条对话，支持切换第四张缩略图", async () => {
  batch.phase="completed";
  tasks=[{id:"b".repeat(32),name:"四张图",prompt:"same",refs:[],temperature:null,aspect_ratio:"16:9",image_size:"1K",image_count:4,generation_config:{}}];
  const base=vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async(path,method,body)=>{
    if(path.endsWith("/results"))return {tasks:[{task_id:tasks[0].id,name:tasks[0].name,state:"succeeded",total_requests:4,completed_requests:4,succeeded_requests:4,error:null,
      images:Array.from({length:4},(_,i)=>({path:`D:/output/result-${i}.png`,mime_type:"image/png",sha256:String(i).repeat(64),size:100}))}],counts:{succeeded:1,images:4},final:true,row_errors:[]} as never;
    return base(path,method,body);
  });
  const user=userEvent.setup();render(<App />);
  await screen.findByRole("button",{name:"查看第 4 张"});
  expect(document.querySelectorAll(".task-card")).toHaveLength(1);
  expect(screen.getByLabelText("生成请求进度").textContent).toBe("4/4");
  await user.click(screen.getByRole("button",{name:"查看第 4 张"}));
  await waitFor(()=>expect(screen.getByRole("img",{name:"四张图 第 4 张"}).getAttribute("src")).toContain(`/images/${tasks[0].id}/3`));
});
