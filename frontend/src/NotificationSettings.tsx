import { useEffect, useRef, useState } from "react";
import { Bell, Check, Music2, Play, Upload } from "lucide-react";
import { api } from "./api";
import { Picker } from "./components";
import { usePreferences } from "./preferences";
import type { NotificationPreferences } from "./types";

export const notificationDefaults: NotificationPreferences = {
  enabled: true, mode: "all", image_batches: true, harness_tasks: true,
  include_failures: true, sound_enabled: true, sound: "soft",
  custom_sound_id: null, custom_sound_name: null,
};

export function NotificationSettings() {
  const { preferences, update } = usePreferences();
  const english = preferences.language === "en";
  const text = (zh: string, en: string) => english ? en : zh;
  const value = { ...notificationDefaults, ...preferences.notifications };
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [available, setAvailable] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    let active = true;
    void api<{available: boolean; last_error: string | null}>("/notifications/status")
      .then(status => { if(active) {setAvailable(status.available); setError(status.last_error || "");} })
      .catch(e => { if(active) setError(String(e.message || e)); });
    return () => { active = false; };
  }, []);
  async function run(action: () => Promise<void>) {
    if(busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await action(); }
    catch(e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const save = (patch: Partial<NotificationPreferences>) => run(async () => {
    await update({ notifications: { ...value, ...patch } });
  });
  function toggle(label: string, checked: boolean, key: keyof NotificationPreferences, disabled=false) {
    return <div className="setting-row">
      <span>{label}</span>
      <button type="button" role="switch" aria-label={label} aria-checked={checked}
        disabled={busy || disabled || !available}
        className={"setting-switch " + (checked ? "checked" : "")}
        onClick={() => void save({[key]: !checked})}><span /></button>
    </div>;
  }
  async function upload(file: File) {
    await run(async () => {
      if(file.size > 5 * 1024 * 1024) throw Error(text("音频不能超过 5 MB", "Audio must be 5 MB or smaller"));
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for(let offset=0; offset<bytes.length; offset+=32768)
        binary += String.fromCharCode(...bytes.subarray(offset, offset+32768));
      const imported = await api<{custom_sound_id:string;custom_sound_name:string}>("/notifications/sound", "POST", {
        name:file.name, content_base64:btoa(binary),
      });
      await update({notifications:{...value,...imported,sound:"custom"}});
      setMessage(text("自定义声音已保存", "Custom sound saved"));
    });
  }
  return <section className="notification-settings">
    <div className="settings-subheading"><Bell size={17}/>{text("完成提醒", "Completion reminders")}</div>
    {toggle(text("启用完成提醒", "Enable completion reminders"), value.enabled, "enabled")}
    <div className={"notification-options " + (!value.enabled ? "notification-options-muted" : "")}>
      <div className="notification-label">{text("提醒时机", "Notify me when")}</div>
      <div className="notification-mode" role="group" aria-label={text("提醒时机", "Notify me when")}>
        {(["all", "each"] as const).map(mode => <button key={mode} type="button"
          disabled={busy || !value.enabled} aria-pressed={value.mode === mode}
          className={value.mode === mode ? "selected" : ""} onClick={() => void save({mode})}>
          <span>{mode === "all" ? text("所有批次完成", "All batches finish") : text("每批次完成", "Each batch finishes")}</span>
          {value.mode === mode && <Check size={15}/>}</button>)}
      </div>
      {toggle(text("生图批次", "Image batches"),value.image_batches,"image_batches",!value.enabled)}
      {toggle(text("Harness 任务", "Harness tasks"),value.harness_tasks,"harness_tasks",!value.enabled)}
      {toggle(text("失败时也提醒", "Also notify on failure"),value.include_failures,"include_failures",!value.enabled)}
      <div className="settings-divider"/>
      {toggle(text("提醒声音", "Play a sound"),value.sound_enabled,"sound_enabled",!value.enabled)}
      <div className="notification-sound-row">
        <Music2 size={17}/>
        <Picker label={text("提醒声音", "Notification sound")} value={value.sound}
          disabled={busy || !value.enabled || !value.sound_enabled}
          options={[
            {value:"soft",label:text("清音", "Soft")},
            {value:"chime",label:text("风铃", "Chime")},
            {value:"double",label:text("双音", "Double")},
            ...(value.custom_sound_id ? [{value:"custom",label:text("自定义", "Custom")}] : []),
          ]}
          onChange={sound => void save({sound:sound as NotificationPreferences["sound"]})}/>
        <button type="button" className="secondary-button" disabled={busy || !value.enabled || !value.sound_enabled}
          onClick={() => void run(async () => {await api("/notifications/test","POST",{sound_only:true});})}>
          <Play size={14}/>{text("试听", "Listen")}</button>
        <button type="button" className="secondary-button" disabled={busy || !value.enabled || !value.sound_enabled}
          onClick={() => input.current?.click()}><Upload size={14}/>{text("导入声音", "Import sound")}</button>
      </div>
      {value.custom_sound_name && <p className="notification-file" title={value.custom_sound_name}>{value.custom_sound_name}</p>}
      <input ref={input} hidden type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" onChange={event => {
        const file=event.target.files?.[0]; event.target.value=""; if(file) void upload(file);
      }}/>
    </div>
    {!available && <p className="settings-error">{text("此功能需要 Windows 桌面环境。", "This feature requires Windows.")}</p>}
    <div className="notification-test-row">
      <button type="button" className="secondary-button" disabled={busy || !available} onClick={() => void run(async () => {
        await api("/notifications/test","POST",{sound_only:false});
        setMessage(text("测试提醒已发送到 Windows", "Test notification sent to Windows"));
      })}><Bell size={15}/>{text("发送测试提醒", "Send test notification")}</button>
    </div>
    {error && <p className="settings-error" role="alert">{error}</p>}
    {message && <p className="settings-success" role="status">{message}</p>}
  </section>;
}
