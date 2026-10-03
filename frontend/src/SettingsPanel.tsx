import { useRef, useState } from "react";
import {
  Archive,
  Check,
  FileKey,
  LoaderCircle,
  LogOut,
  Moon,
  RefreshCw,
  Upload,
} from "lucide-react";
import { api } from "./api";
import { Modal, Picker } from "./components";
import { usePreferences } from "./preferences";
import { useTranslation } from "./i18n";
import type { PublicConfig } from "./types";

export function SettingsPanel({
  config,
  close,
  configured,
  archive,
  checkConnection,
}: {
  config?: PublicConfig;
  close: () => void;
  configured: (value: PublicConfig) => void;
  archive?: () => Promise<void>;
  checkConnection?: () => Promise<void>;
}) {
  const t = useTranslation(),
    { preferences, update } = usePreferences();
  const [tab, setTab] = useState("general"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [project, setProject] = useState(config?.project || ""),
    [bucket, setBucket] = useState(config?.bucket || "");
  const [key, setKey] = useState<File>(),
    [message, setMessage] = useState("");
  const input = useRef<HTMLInputElement>(null);
  async function run(operation: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await operation();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("操作未完成"));
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    await run(async () => {
      const body: {
        project: string;
        bucket: string;
        key_json?: string;
        credential_filename?: string;
      } = { project: project.trim(), bucket: bucket.trim() };
      if (key) {
        if (key.size > 1024 * 1024) throw new Error(t("密钥文件过大"));
        body.key_json = await key.text();
        body.credential_filename = key.name;
      }
      const result = await api<PublicConfig>(
        "/cloud/configuration",
        "PUT",
        body,
      );
      configured(result);
      setKey(undefined);
      setMessage(t("连接已保存"));
    });
  }
  function toggle(
    label: string,
    checked: boolean,
    onChange: (value: boolean) => Promise<void>,
    desktop = false,
  ) {
    return (
      <div className="setting-row">
        <span>{t(label)}</span>
        <button
          type="button"
          role="switch"
          aria-label={t(label)}
          aria-checked={checked}
          disabled={busy || (desktop && !window.studio)}
          title={desktop && !window.studio ? t("仅桌面程序支持") : undefined}
          className={"setting-switch " + (checked ? "checked" : "")}
          onClick={() => void run(() => onChange(!checked))}
        >
          <span />
        </button>
      </div>
    );
  }
  return (
    <Modal title={t("设置")} close={close} wide>
      <div className="settings-panel">
        <nav className="settings-navigation">
          <button
            className={tab === "general" ? "selected" : ""}
            onClick={() => setTab("general")}
          >
            {t("常规")}
          </button>
          <button
            className={tab === "cloud" ? "selected" : ""}
            onClick={() => setTab("cloud")}
          >
            {t("Google Cloud 登录")}
          </button>
        </nav>
        <div className="settings-content">
          {tab === "general" ? (
            <>
              <div className="settings-subheading">
                <Moon size={17} />
                {t("主题")}
              </div>
              {toggle("深色主题", preferences.theme === "dark", (value) =>
                update({ theme: value ? "dark" : "light" }),
              )}
              <div className="setting-row">
                <span>{t("语言")}</span>
                <Picker
                  label={t("语言")}
                  value={preferences.language}
                  onChange={(value) =>
                    void run(() =>
                      update({ language: value as "zh-CN" | "en" }),
                    )
                  }
                  options={[
                    { value: "zh-CN", label: "简体中文" },
                    { value: "en", label: "English" },
                  ]}
                />
              </div>
              <div className="settings-divider" />
              {toggle(
                "关闭时最小化到托盘",
                preferences.close_to_tray,
                (value) => update({ close_to_tray: value }),
                true,
              )}
              {toggle(
                "开机自启动",
                preferences.auto_start,
                (value) => update({ auto_start: value }),
                true,
              )}
              {toggle(
                "启动时最小化至托盘",
                preferences.start_minimized,
                (value) => update({ start_minimized: value }),
                true,
              )}
              {!window.studio && (
                <p className="desktop-only-note">{t("仅桌面程序支持")}</p>
              )}
              <div className="settings-divider" />
              <div className="settings-management">
                {archive && (
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await archive();
                        close();
                      })
                    }
                  >
                    <Archive size={15} />
                    {t("归档当前项目")}
                  </button>
                )}
                {window.studio && (
                  <button
                    className="text-button danger"
                    onClick={() => window.studio!.window("quit")}
                  >
                    <LogOut size={15} />
                    {t("退出工作室")}
                  </button>
                )}
              </div>
            </>
          ) : (
            <form
              className="cloud-form"
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
            >
              <div className="settings-subheading">
                <FileKey size={17} />
                {t("服务账号")}
              </div>
              <label className="form-label">
                {t("项目 ID")}
                <input
                  value={project}
                  onChange={(event) => setProject(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <label className="form-label">
                {t("存储桶")}
                <input
                  value={bucket}
                  onChange={(event) => setBucket(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <div className="credential-row">
                <div>
                  <small>{t("凭证")}</small>
                  <span>
                    {key?.name ||
                      config?.credential_name ||
                      (config?.credentials_configured
                        ? t("已配置")
                        : t("未配置"))}
                  </span>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => input.current?.click()}
                >
                  <Upload size={14} />
                  {t("导入 JSON 密钥")}
                </button>
              </div>
              <input
                ref={input}
                type="file"
                hidden
                accept=".json,application/json"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) {
                    if (file.size > 1024 * 1024) setError(t("密钥文件过大"));
                    else {
                      setKey(file);
                      setError("");
                    }
                  }
                  event.target.value = "";
                }}
              />
              <div className="cloud-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      if (checkConnection) await checkConnection();
                      else await api("/cloud/check", "POST");
                      setMessage(t("连接正常"));
                    })
                  }
                >
                  <RefreshCw size={15} />
                  {t("检查连接")}
                </button>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={busy || !project.trim() || !bucket.trim()}
                >
                  {busy ? (
                    <LoaderCircle size={15} className="spin" />
                  ) : (
                    <Check size={15} />
                  )}{" "}
                  {t("保存连接")}
                </button>
              </div>
            </form>
          )}
          {error && (
            <p className="settings-error" role="alert">
              {error}
            </p>
          )}
          {message && (
            <p className="settings-success" role="status">
              {message}
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
