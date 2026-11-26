import { useLayoutEffect, useRef, useState } from "react";
import type { RefObject, UIEvent } from "react";

const WINDOW_SIZE = 20;
const PAGE_SHIFT = 10;
const EDGE = 48;

type Position = { project: string; start: number };
type ScrollRequest =
  | { type: "latest" }
  | { type: "jump"; id: string; project: string }
  | { type: "preserve"; id: string; offset: number; project: string };

export function useConversationWindow(
  project: string, ids: string[], scroller: RefObject<HTMLDivElement | null>,
) {
  const [position, setPosition] = useState<Position>();
  const [request, setRequest] = useState<ScrollRequest>();
  const pendingScroll = useRef(false);
  const latest = Math.max(0, ids.length - WINDOW_SIZE);
  const jumpIndex = request?.type === "jump" && request.project === project ? ids.indexOf(request.id) : -1;
  const start = jumpIndex >= 0 ? Math.min(latest, Math.max(0, jumpIndex - PAGE_SHIFT))
    : request?.type === "latest" || position?.project !== project ? latest
    : Math.min(latest, position.start);
  const end = Math.min(ids.length, start + WINDOW_SIZE);
  const previous = start > 0;
  const next = end < ids.length;
  const lastProject = useRef("");
  const lastNewest = useRef<string | undefined>(undefined);
  const lastLength = useRef(0);
  const follow = useRef(true);

  useLayoutEffect(() => {
    const view = scroller.current;
    if (!view) return;
    const changedProject = lastProject.current !== project;
    const newestId = ids.at(-1);
    if (changedProject) follow.current = true;
    if (request?.type === "jump" && jumpIndex >= 0) {
      const card = document.getElementById("task-" + request.id);
      if (card && view.contains(card)) {
        view.scrollTop += card.getBoundingClientRect().top -
          view.getBoundingClientRect().top - Math.max(0, (view.clientHeight - card.clientHeight) / 2);
        follow.current = false;
        setPosition({ project, start });
        setRequest(undefined);
      }
    } else if (request?.type === "preserve" && request.project === project) {
      const card = document.getElementById("task-" + request.id);
      if (card && view.contains(card)) {
        view.scrollTop += card.getBoundingClientRect().top -
          view.getBoundingClientRect().top - request.offset;
      }
      setRequest(undefined);
    } else if (request?.type === "latest" ||
        (!next && follow.current && ids.length > WINDOW_SIZE &&
          (changedProject || lastNewest.current !== newestId || lastLength.current !== ids.length))) {
      view.scrollTop = view.scrollHeight;
      follow.current = true;
      if (request?.type === "latest") {
        setPosition(undefined);
        setRequest(undefined);
      }
    }
    lastProject.current = project;
    lastNewest.current = newestId;
    lastLength.current = ids.length;
    pendingScroll.current = false;
  }, [project, ids, scroller, request, jumpIndex, start, next]);

  function page(direction: -1 | 1) {
    const view = scroller.current;
    if (!view || pendingScroll.current) return;
    const newStart = Math.min(latest, Math.max(0, start + direction * PAGE_SHIFT));
    if (newStart === start) return;
    const top = view.getBoundingClientRect().top;
    const bottom = top + view.clientHeight;
    const anchor = ids.slice(Math.max(start, newStart), Math.min(end, newStart + WINDOW_SIZE))
      .map(id => ({ id, rect: document.getElementById("task-" + id)?.getBoundingClientRect() }))
      .find(({ rect }) => rect && rect.bottom > top && rect.top < bottom);
    // Keep the first visible shared card. If the view is too tall or a button
    // was used far from the boundary, the closest shared card is the anchor.
    const fallback = ids[direction < 0 ? start : newStart];
    const id = anchor?.id ?? fallback;
    const offset = anchor?.rect ? anchor.rect.top - top : 28;
    pendingScroll.current = true;
    follow.current = false;
    setPosition(newStart === latest ? undefined : { project, start: newStart });
    setRequest({ type: "preserve", id, offset, project });
  }

  function onScroll(event: UIEvent<HTMLDivElement>) {
    const view = event.currentTarget;
    if (pendingScroll.current || request || !view.clientHeight) return;
    const nearBottom = view.scrollHeight - view.clientHeight - view.scrollTop <= EDGE;
    follow.current = !next && nearBottom;
    if (previous && view.scrollTop < EDGE) page(-1);
    else if (next && nearBottom) page(1);
  }

  return {
    start, end, previous, next, page, onScroll,
    jump: (targetProject: string, id: string) => setRequest({ type: "jump", id, project: targetProject }),
    latest: () => setRequest({ type: "latest" }),
  };
}
