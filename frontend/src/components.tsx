import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, X } from "lucide-react";
import { imageUrl } from "./api";
import { useTranslation } from "./i18n";

export function Media({
  path,
  alt,
  className = "",
  onClick,
}: {
  path: string;
  alt: string;
  className?: string;
  onClick?: () => void;
}) {
  const t = useTranslation();
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setFailed(false);
    setSrc("");
    void imageUrl(path)
      .then((value) => {
        if (active) setSrc(value);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [path]);
  return failed ? (
    <span className="media-error">{t("图片暂不可用")}</span>
  ) : src ? (
    <img
      src={src}
      alt={alt}
      className={className}
      onClick={onClick}
      onError={() => setFailed(true)}
    />
  ) : (
    <span className={"media-loading " + className} />
  );
}
export interface Option {
  value: string;
  label: string;
}
export function Picker({
  label,
  value,
  onChange,
  groups,
  options,
  icon,
  unit,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options?: Option[];
  groups?: { label: string; options: Option[] }[];
  icon?: ReactNode;
  unit?: string;
  className?: string;
}) {
  const t = useTranslation();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const all = [
    ...(groups?.flatMap((group) => group.options) || []),
    ...(options || []),
  ];
  const current = all.find((option) => option.value === value)?.label || value;
  useLayoutEffect(() => {
    if (!open || !trigger.current || !menu.current) return;
    const place = () => {
      if (!trigger.current || !menu.current) return;
      const anchor = trigger.current.getBoundingClientRect(),
        popup = menu.current.getBoundingClientRect();
      setPosition({
        left: Math.max(8, Math.min(anchor.left, innerWidth - popup.width - 8)),
        top: Math.max(
          8,
          anchor.top >= popup.height + 12
            ? anchor.top - popup.height - 8
            : Math.min(anchor.bottom + 8, innerHeight - popup.height - 8),
        ),
      });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !menu.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
    };
  }, [open]);
  const renderOption = (option: Option) => (
    <button
      key={option.value}
      role="option"
      aria-selected={option.value === value}
      onClick={() => {
        onChange(option.value);
        setOpen(false);
        trigger.current?.focus();
      }}
    >
      <span>{option.label}</span>
      {option.value === value && <Check size={13} aria-hidden />}
    </button>
  );
  return (
    <span className={"picker-wrap " + className}>
      <button
        ref={trigger}
        type="button"
        className="picker-trigger"
        aria-label={`${label}：${current}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setTimeout(
              () =>
                menu.current
                  ?.querySelector<HTMLButtonElement>('[aria-selected="true"]')
                  ?.focus(),
              0,
            );
          }
        }}
      >
        {icon}
        <span>{current}</span>
        <ChevronDown size={13} className={open ? "turned" : ""} aria-hidden />
      </button>
      {unit && <span className="picker-unit">{unit}</span>}
      {open &&
        createPortal(
          <div
            ref={menu}
            className={"picker-menu " + (groups ? "ratio-menu" : "")}
            role="listbox"
            aria-label={`${label}${t("选项")}`}
            style={position}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setOpen(false);
                trigger.current?.focus();
                return;
              }
              if (event.key === "Tab") {
                setOpen(false);
                trigger.current?.focus();
                return;
              }
              const buttons = Array.from(
                menu.current!.querySelectorAll<HTMLButtonElement>(
                  '[role="option"]',
                ),
              );
              const i = buttons.indexOf(
                document.activeElement as HTMLButtonElement,
              );
              const next =
                event.key === "ArrowDown"
                  ? (i + 1) % buttons.length
                  : event.key === "ArrowUp"
                    ? (i - 1 + buttons.length) % buttons.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? buttons.length - 1
                        : -1;
              if (next >= 0) {
                event.preventDefault();
                buttons[next].focus();
              }
            }}
          >
            {groups && (
              <div className="ratio-columns">
                {groups.map((group) => (
                  <div key={group.label} role="group" aria-label={group.label}>
                    <div className="ratio-heading">{group.label}</div>
                    {group.options.map(renderOption)}
                  </div>
                ))}
              </div>
            )}
            {options && (
              <div className={groups ? "ratio-footer" : ""}>
                {options.map(renderOption)}
              </div>
            )}
          </div>,
          document.body,
        )}
    </span>
  );
}
export function Modal({
  title,
  children,
  close,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  const t = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>("input,button,textarea")?.focus();
    return () => previous?.focus();
  }, []);
  return createPortal(
    <div
      className="modal-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={box}
        className={"modal " + (wide ? "modal-wide" : "")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(event) => {
          if (event.key === "Escape") close();
          if (event.key === "Tab") {
            const elements = Array.from(
              box.current!.querySelectorAll<HTMLElement>(
                "button:not(:disabled), input, textarea, a[href]",
              ),
            );
            if (event.shiftKey && document.activeElement === elements[0]) {
              event.preventDefault();
              elements.at(-1)?.focus();
            }
            if (!event.shiftKey && document.activeElement === elements.at(-1)) {
              event.preventDefault();
              elements[0]?.focus();
            }
          }
        }}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button
            className="icon-button"
            onClick={close}
            aria-label={t("关闭弹窗")}
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
