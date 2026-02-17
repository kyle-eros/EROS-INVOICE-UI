import type { ReactNode } from "react";

export interface DataColumn<RowType> {
  id: string;
  header: string;
  align?: "left" | "right";
  className?: string;
  render: (row: RowType) => ReactNode;
}

export interface DataTableProps<RowType> {
  caption: string;
  columns: DataColumn<RowType>[];
  rows: RowType[];
  rowKey: (row: RowType) => string;
}

export function DataTable<RowType>({ caption, columns, rows, rowKey }: DataTableProps<RowType>) {
  return (
    <div className="data-table-shell">
      <table className="data-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.id}
                scope="col"
                className={[column.className, column.align === "right" ? "is-right" : ""].filter(Boolean).join(" ")}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);

            return (
              <tr key={key}>
                {columns.map((column) => (
                  <td
                    key={`${key}-${column.id}`}
                    className={[column.className, column.align === "right" ? "is-right" : ""].filter(Boolean).join(" ")}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
