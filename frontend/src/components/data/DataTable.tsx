import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { EmptyState } from "./EmptyState";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
}

/** A table that becomes stacked label/value cards below 640px (spec s6). */
export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  emptyMessage = "No rows to show.",
  className,
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowKey: (row: T) => string;
  emptyMessage?: string;
  className?: string;
}) {
  if (rows.length === 0) return <EmptyState title={emptyMessage} />;

  return (
    <div className={className}>
      <div className="flex flex-col gap-2 sm:hidden">
        {rows.map((row) => (
          <div key={getRowKey(row)} className="rounded-control border border-line bg-surface-2 p-3">
            {columns.map((column) => (
              <div key={column.key} className="flex items-center justify-between gap-3 py-1 text-sm">
                <span className="text-xs text-ink-faint">{column.header}</span>
                <span className="text-right text-ink">{column.cell(row)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <table className="hidden w-full text-left text-sm sm:table">
        <thead>
          <tr className="border-b border-line text-xs text-ink-faint">
            {columns.map((column) => (
              <th key={column.key} className={cn("px-3 py-2 font-medium", column.className)}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={getRowKey(row)} className="hover:bg-surface-2/60">
              {columns.map((column) => (
                <td key={column.key} className={cn("px-3 py-2 text-ink", column.className)}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
