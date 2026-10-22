export interface MessageBatcher<T> {
  /** Adds an item to its chat's pending batch, resetting the flush timer. */
  add(chatId: string, item: T): void;
}

export interface MessageBatcherOptions<T> {
  /** How long to wait after the latest add before flushing. */
  windowMs: number;
  /** Handles one chat's batch. Errors are caught and logged, never thrown. */
  onFlush: (chatId: string, items: T[]) => Promise<void>;
}

interface PendingBatch<T> {
  items: T[];
  timer: ReturnType<typeof setTimeout> | undefined;
}

export function createMessageBatcher<T>({
  windowMs,
  onFlush,
}: MessageBatcherOptions<T>): MessageBatcher<T> {
  const pending = new Map<string, PendingBatch<T>>();

  async function flush(chatId: string, batch: PendingBatch<T>): Promise<void> {
    // Remove first: a message arriving while this flush runs starts its own window.
    pending.delete(chatId);
    try {
      await onFlush(chatId, batch.items);
    } catch (error) {
      console.error(`failed to flush messages for chat ${chatId}`, error);
    }
  }

  function schedule(chatId: string, batch: PendingBatch<T>): void {
    if (batch.timer !== undefined) clearTimeout(batch.timer);
    batch.timer = setTimeout(() => void flush(chatId, batch), windowMs);
  }

  return {
    add(chatId, item) {
      const batch = pending.get(chatId);
      if (batch) {
        batch.items.push(item);
        schedule(chatId, batch);
        return;
      }
      const created: PendingBatch<T> = { items: [item], timer: undefined };
      pending.set(chatId, created);
      schedule(chatId, created);
    },
  };
}
