export function downloadJson(
  filename: string,
  payload: unknown,
  options: { pretty?: boolean } = {},
): void {
  const json = options.pretty
    ? JSON.stringify(payload, null, 2)
    : JSON.stringify(payload);
  const url = URL.createObjectURL(new Blob(
    [json],
    { type: 'application/json;charset=utf-8' },
  ));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
