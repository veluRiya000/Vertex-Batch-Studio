import { afterEach, beforeEach, it, expect, vi } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "./api";
import { SettingsPanel } from "./SettingsPanel";
import { PreferencesProvider, defaults } from "./preferences";
vi.mock("./api", () => ({ api: vi.fn() }));
beforeEach(() => {
  localStorage.clear();
  delete window.studio;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/preferences")
      return (method === "PUT" ? body : defaults) as never;
    if (path === "/cloud/configuration")
      return {
        project: "demo",
        bucket: "bucket",
        credential_name: "downloaded.json",
        credentials_configured: true,
      } as never;
    throw new Error("Unexpected request " + path);
  });
});
afterEach(() => {
  cleanup();
  document.documentElement.dataset.theme = "light";
  document.documentElement.lang = "zh-CN";
});
const config = {
  project: "demo",
  bucket: "bucket",
  model: "gemini-3.1-flash-image",
  location: "global",
  data_dir: "D:/data",
  root: "D:/studio",
  poll_seconds: 30,
  credentials_configured: false,
};
it("主题与语言实际应用并保存，浏览器禁用桌面专属开关", async () => {
  const user = userEvent.setup();
  render(
    <PreferencesProvider>
      <SettingsPanel config={config} close={() => {}} configured={() => {}} />
    </PreferencesProvider>,
  );
  await user.click(screen.getByRole("switch", { name: "深色主题" }));
  await waitFor(() =>
    expect(document.documentElement.dataset.theme).toBe("dark"),
  );
  expect(
    (screen.getByRole("switch", { name: "开机自启动" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  await user.click(screen.getByRole("button", { name: "语言：简体中文" }));
  await user.click(screen.getByRole("option", { name: "English" }));
  await screen.findByRole("dialog", { name: "Settings" });
  expect(screen.getByRole("switch", { name: "Dark theme" })).toBeTruthy();
  expect(JSON.parse(localStorage.getItem("vbs-preferences")!).language).toBe(
    "en",
  );
});
it("任意名称的 JSON 密钥导入后提交内容，界面不显示密钥", async () => {
  const user = userEvent.setup(),
    configured = vi.fn();
  const { container } = render(
    <PreferencesProvider>
      <SettingsPanel config={config} close={() => {}} configured={configured} />
    </PreferencesProvider>,
  );
  await user.click(screen.getByRole("button", { name: "Google Cloud 登录" }));
  const privateText = '{"private_key":"disposable-test-marker"}';
  const file = new File([privateText], "downloaded-project-123.json", {
    type: "application/json",
  });
  Object.defineProperty(file, "text", { value: async () => privateText });
  // The modal is portalled, so locate the file control in the document.
  await user.upload(
    document.querySelector(".cloud-form input[type=file]") as HTMLInputElement,
    file,
  );
  expect(screen.getByText("downloaded-project-123.json")).toBeTruthy();
  expect(document.body.textContent).not.toContain("disposable-test-marker");
  await user.click(screen.getByRole("button", { name: "保存连接" }));
  await waitFor(() => expect(configured).toHaveBeenCalledOnce());
  const call = vi
    .mocked(api)
    .mock.calls.find(([path]) => path === "/cloud/configuration")!;
  expect(call[2]).toEqual({
    project: "demo",
    bucket: "bucket",
    credential_filename: file.name,
    key_json: privateText,
  });
  expect(screen.getByRole("status").textContent).toBe("连接已保存");
});
