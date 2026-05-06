/**
 * Favorites localStorage helper for query history
 * Client-side storage (no backend required for MVP)
 */

const FAVORITES_KEY = 'datapond_favorite_queries'
const MAX_FAVORITES = 50

export function getFavoriteQueries(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const stored = localStorage.getItem(FAVORITES_KEY)
    return stored ? JSON.parse(stored) : []
  } catch (error) {
    console.error('Failed to load favorites:', error)
    return []
  }
}

export function addFavorite(queryId: string): void {
  if (typeof window === 'undefined') return
  try {
    const favorites = getFavoriteQueries()
    if (!favorites.includes(queryId)) {
      favorites.unshift(queryId)
      if (favorites.length > MAX_FAVORITES) {
        favorites.pop() // FIFO eviction
      }
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites))
    }
  } catch (error) {
    console.error('Failed to add favorite:', error)
  }
}

export function removeFavorite(queryId: string): void {
  if (typeof window === 'undefined') return
  try {
    let favorites = getFavoriteQueries()
    favorites = favorites.filter(id => id !== queryId)
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites))
  } catch (error) {
    console.error('Failed to remove favorite:', error)
  }
}

export function isFavorite(queryId: string): boolean {
  return getFavoriteQueries().includes(queryId)
}

export function toggleFavorite(queryId: string): boolean {
  const isFav = isFavorite(queryId)
  if (isFav) {
    removeFavorite(queryId)
  } else {
    addFavorite(queryId)
  }
  return !isFav
}
