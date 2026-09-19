import { useLayoutEffect, useState } from "react";

/**
 * The rendered width of an element, kept current as it resizes.
 *
 * Charts draw in real pixels rather than a fixed viewBox: a scaled viewBox
 * letterboxes inside a wide panel and puts pointer coordinates in a different
 * space from the marks. A callback ref, so it attaches whenever the element
 * mounts (charts render a placeholder until they have data).
 */
export function useElementWidth(fallback: number) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [width, setWidth] = useState(fallback);

  useLayoutEffect(() => {
    if (!element) return;
    const measure = () => {
      const next = Math.round(element.getBoundingClientRect().width);
      if (next > 0) setWidth(next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);

  return { ref: setElement, width };
}
