/**
 * Returns the base URL of the current deployment.
 * Works regardless of domain/IP — always uses window.location.
 * Falls back to env var for SSR contexts.
 */
export function baseUrl(): string {
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.host}`
  }
  // SSR fallback — not used for external links (client-only pages)
  return process.env.NEXT_PUBLIC_FRONTEND_URL ?? "http://datapond.local"
}

export const serviceUrls = {
  jupyter:      () => `${baseUrl()}/jupyter`,
  airflow:      () => `${baseUrl()}/airflow`,
  mlflow:       () => `${baseUrl()}/mlflow`,
  openmetadata: () => `${baseUrl()}/openmetadata`,
  minio:        () => `${baseUrl()}/storage`,
  api:          () => `${baseUrl()}/api`,
}
