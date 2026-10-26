export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const body = response.status === 204 ? undefined : await response.json();
  if (!response.ok) throw new ApiError(response.status, body?.detail ?? "Request failed");
  return body as T;
}

export type Account = { id: string; username: string };
export type Workspace = { id: string; name: string; role: string; can_create_collections: boolean; can_import_folders: boolean; can_manage_index: boolean; can_view_analytics: boolean };
export type Source = { id: string; name: string; connector_kind: string; status: string; can_ingest: boolean; can_admin: boolean };

export async function apiPage<T>(path: string): Promise<{items:T[]; next:string; total:number}> {
  const response=await fetch(path,{credentials:"same-origin"});
  const body=await response.json();
  if(!response.ok)throw new ApiError(response.status,body?.detail??"Request failed");
  return {items:body as T[],next:response.headers.get("X-Next-Cursor")??"",total:Number(response.headers.get("X-Total-Count")??0)};
}
