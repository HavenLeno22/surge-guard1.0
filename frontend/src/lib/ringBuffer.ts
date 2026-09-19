/**
 * A fixed-capacity buffer that keeps only the newest items.
 *
 * Used for session trends: a control-room tab stays open for a shift, and an
 * unbounded array of samples is a leak with a deadline.
 */
export class RingBuffer<T> {
  private readonly items: (T | undefined)[];
  private start = 0;
  private length = 0;

  constructor(readonly capacity: number) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new Error("RingBuffer capacity must be a positive integer");
    }
    this.items = new Array<T | undefined>(capacity);
  }

  get size(): number {
    return this.length;
  }

  push(item: T): void {
    const index = (this.start + this.length) % this.capacity;
    this.items[index] = item;
    if (this.length < this.capacity) {
      this.length += 1;
    } else {
      this.start = (this.start + 1) % this.capacity;
    }
  }

  /** Oldest first. */
  toArray(): T[] {
    const result: T[] = [];
    for (let offset = 0; offset < this.length; offset += 1) {
      result.push(this.items[(this.start + offset) % this.capacity] as T);
    }
    return result;
  }

  last(): T | undefined {
    if (this.length === 0) return undefined;
    return this.items[(this.start + this.length - 1) % this.capacity];
  }

  clear(): void {
    this.items.fill(undefined);
    this.start = 0;
    this.length = 0;
  }
}
