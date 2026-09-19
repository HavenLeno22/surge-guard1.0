import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { SnapshotImage } from "./SnapshotImage";

describe("SnapshotImage", () => {
  test("says there is no picture when the snapshot fails, and recovers on the next frame", () => {
    render(<SnapshotImage cameraId="cam-02" layers={[]} alt="Queue Side View" />);
    const image = screen.getByAltText("Queue Side View");
    expect(image.getAttribute("src")).toContain("/cameras/cam-02/snapshot");

    fireEvent.error(image);
    expect(screen.getByText("No picture from this camera right now")).toBeInTheDocument();

    fireEvent.load(image);
    expect(screen.queryByText("No picture from this camera right now")).not.toBeInTheDocument();
  });

  test("requests nothing while paused", () => {
    render(<SnapshotImage cameraId="cam-02" layers={[]} alt="Queue Side View" active={false} />);
    expect(screen.queryByAltText("Queue Side View")).not.toBeInTheDocument();
  });
});
