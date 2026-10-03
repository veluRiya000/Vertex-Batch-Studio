import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { Preferences } from "./types";

export const defaults: Preferences = {
  theme: "light",
  language: "zh-CN",
  close_to_tray: true,
  auto_start: false,
  start_minimized: false,
  sidebar_width: 258,
};
const Context = createContext({
  preferences: defaults,
  update: async (_values: Partial<Preferences>) => {},
});
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<Preferences>(() => {
    try {
      return {
        ...defaults,
        ...JSON.parse(localStorage.getItem("vbs-preferences") || "{}"),
      };
    } catch {
      return defaults;
    }
  });
  const current = useRef(preferences),
    chain = useRef(Promise.resolve()),
    revision = useRef(0);
  current.current = preferences;
  useEffect(() => {
    void api<Preferences>("/preferences")
      .then((value) => {
        if (revision.current === 0) setPreferences(value);
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme;
    document.documentElement.lang = preferences.language;
    localStorage.setItem("vbs-preferences", JSON.stringify(preferences));
  }, [preferences]);
  function update(values: Partial<Preferences>): Promise<void> {
    revision.current++;
    // Serialize saves so dragging the sidebar and changing another setting cannot overwrite each other.
    const operation = chain.current
      .catch(() => {})
      .then(async () => {
        const next = { ...current.current, ...values };
        const saved = window.studio
          ? await window.studio.setPreferences(next)
          : await api<Preferences>("/preferences", "PUT", next);
        current.current = saved;
        setPreferences(saved);
      });
    chain.current = operation;
    return operation;
  }
  return (
    <Context.Provider value={{ preferences, update }}>
      {children}
    </Context.Provider>
  );
}
export const usePreferences = () => useContext(Context);
