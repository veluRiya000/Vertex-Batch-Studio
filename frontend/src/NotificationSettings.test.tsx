import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {cleanup,render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {api} from "./api";
import {PreferencesProvider,defaults} from "./preferences";
import {SettingsPanel} from "./SettingsPanel";
vi.mock("./api",()=>({api:vi.fn()}));
beforeEach(()=>{
  localStorage.clear(); delete window.studio; vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async(path,method,body)=>{
    if(path==="/preferences") return (method==="PUT"?body:defaults) as never;
    if(path==="/notifications/status") return {available:true,last_error:null} as never;
    if(path==="/notifications/test") return {sent:true} as never;
    if(path==="/notifications/sound") return {custom_sound_id:"a".repeat(64)+".wav",custom_sound_name:"own.wav"} as never;
    throw Error("Unexpected route "+path);
  });
});
afterEach(cleanup);
const open=()=>render(<PreferencesProvider><SettingsPanel initialTab="notifications" close={()=>{}} configured={()=>{}}/></PreferencesProvider>);
it("saves notification choices without losing desktop preferences",async()=>{
  const user=userEvent.setup();open();
  await screen.findByRole("switch",{name:"启用完成提醒"});
  await waitFor(()=>expect(screen.getByRole("switch",{name:"启用完成提醒"}).getAttribute("aria-checked")).toBe("true"));
  await user.click(screen.getByRole("button",{name:"每批次完成"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"每批次完成"}).getAttribute("aria-pressed")).toBe("true"));
  await user.click(screen.getByRole("switch",{name:"失败时也提醒"}));
  const saved=JSON.parse(localStorage.getItem("vbs-preferences")!);
  expect(saved.close_to_tray).toBe(true);
  expect(saved.notifications).toMatchObject({enabled:true,mode:"each",include_failures:false});
});
it("imports a custom sound and keeps preview as an explicit action",async()=>{
  const user=userEvent.setup();open();
  await waitFor(()=>expect(screen.getByRole("switch",{name:"启用完成提醒"}).getAttribute("aria-checked")).toBe("true"));
  const file=new File(["RIFF-test"],"own.wav",{type:"audio/wav"});
  Object.defineProperty(file,"arrayBuffer",{value:async()=>new TextEncoder().encode("RIFF-test").buffer});
  await user.upload(document.querySelector('.notification-settings input[type=file]') as HTMLInputElement,file);
  await screen.findByText("自定义声音已保存");
  expect(JSON.parse(localStorage.getItem("vbs-preferences")!).notifications.sound).toBe("custom");
  expect(vi.mocked(api).mock.calls.filter(([p])=>p==="/notifications/test")).toHaveLength(0);
  await user.click(screen.getByRole("button",{name:"发送测试提醒"}));
  await screen.findByText("测试提醒已发送到 Windows");
  expect(vi.mocked(api).mock.calls.find(([p])=>p==="/notifications/test")?.[2]).toEqual({sound_only:false});
});
