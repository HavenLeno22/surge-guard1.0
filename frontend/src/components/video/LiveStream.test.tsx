import { act, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, test } from "vitest";

import { LiveStream } from "./LiveStream";

function setTabVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function streamImage(cameraId: string): HTMLImageElement {
  return screen.getByAltText(`Live view: camera ${cameraId}`) as HTMLImageElement;
}

// Chrome keeps downloading an MJPEG response after its <img> leaves the page,
// so every removed stream image must be pointed away from the stream first.
function expectStreamReleased(image: HTMLImageElement) {
  expect(image.getAttribute("src")).not.toContain("/stream");
}

describe("LiveStream", () => {
  afterEach(() => setTabVisibility("visible"));

  test("releases its MJPEG connection while the browser tab is hidden, and reconnects on return", () => {
    render(<LiveStream cameraId="73839" layers={["hud"]} running />);
    const first = streamImage("73839");
    expect(first.getAttribute("src")).toContain("/cameras/73839/stream");

    // A hidden tab must not hold one of the browser's ~6 per-origin connections.
    setTabVisibility("hidden");
    expect(screen.queryByAltText("Live view: camera 73839")).not.toBeInTheDocument();
    expectStreamReleased(first);

    setTabVisibility("visible");
    expect(streamImage("73839").getAttribute("src")).toContain("/cameras/73839/stream");
  });

  test("keeps streaming under StrictMode, whose simulated detach must not blank the live image", () => {
    // The app renders in StrictMode (main.tsx): React detaches and re-attaches refs once in dev.
    render(
      <StrictMode>
        <LiveStream cameraId="cam-01" layers={["hud"]} running />
      </StrictMode>,
    );
    expect(streamImage("cam-01").getAttribute("src")).toContain("/cameras/cam-01/stream");
  });

  test("stops the previous camera's stream when switching camera", () => {
    const { rerender } = render(<LiveStream cameraId="cam-01" layers={["hud"]} running />);
    const previous = streamImage("cam-01");

    rerender(<LiveStream cameraId="73839" layers={["hud"]} running />);

    expectStreamReleased(previous);
    expect(streamImage("73839").getAttribute("src")).toContain("/cameras/73839/stream");
  });

  test("stops the old stream when the overlay layers change", () => {
    const { rerender } = render(<LiveStream cameraId="cam-01" layers={["hud"]} running />);
    const previous = streamImage("cam-01");

    rerender(<LiveStream cameraId="cam-01" layers={["hud", "tracks"]} running />);

    expectStreamReleased(previous);
    expect(streamImage("cam-01").getAttribute("src")).toContain("layers=hud%2Ctracks");
  });

  test("stops the stream when it unmounts", () => {
    const { unmount } = render(<LiveStream cameraId="cam-01" layers={["hud"]} running />);
    const image = streamImage("cam-01");

    unmount();

    expectStreamReleased(image);
  });

  test("opens no connection while not running", () => {
    render(<LiveStream cameraId="73839" layers={["hud"]} running={false} />);
    expect(screen.queryByAltText("Live view: camera 73839")).not.toBeInTheDocument();
    expect(screen.getByText("Video paused")).toBeInTheDocument();
  });
});
