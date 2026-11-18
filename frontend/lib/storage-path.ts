/** Folder paths in the Storage browser. Keys use "/" folders; a prefix ends with "/". */

export function breadcrumbs(prefix: string): { name: string; prefix: string }[] {
  const parts = prefix.split("/").filter(Boolean)
  return parts.map((name, i) => ({ name, prefix: parts.slice(0, i + 1).join("/") + "/" }))
}

export function joinKey(prefix: string, name: string): string {
  return `${prefix}${name}`.replace(/^\/+/, "")
}

/** A hint only: the server decides (it looks for metadata/*.metadata.json). True for a
 *  folder holding both data/ and metadata/, or anywhere under such a folder's parts. */
export function looksLikeTable(prefix: string, folderNames: string[]): boolean {
  if (folderNames.includes("metadata") && folderNames.includes("data")) return true
  return /(^|\/)(data|metadata)\//.test(prefix)
}
