/**
 * Highlight utility for text search
 *
 * Provides functions for:
 * - HTML escaping (XSS prevention)
 * - Regex escaping (special character handling)
 * - Text highlighting with search query
 */

/**
 * Result of highlighting text
 */
export interface HighlightResult {
  /** HTML string with highlighted matches */
  html: string;
  /** Whether any match was found */
  hasMatch: boolean;
  /** Number of matches found */
  matchCount: number;
}

/**
 * Escape HTML special characters to prevent XSS
 * @param text - Raw text to escape
 * @returns HTML-safe string
 */
export function escapeHtml(text: string): string {
  if (!text) return '';

  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Escape special regex characters
 * @param str - String to escape
 * @returns Regex-safe string
 */
export function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Highlight search query matches in text
 *
 * @param text - Original text to search in
 * @param query - Search query to highlight
 * @param highlightClass - CSS class for highlight (default: 'bg-highlight')
 * @returns HighlightResult with HTML string and match information
 *
 * @example
 * ```ts
 * const result = highlightText('Hello World', 'world');
 * // result.html: 'Hello <mark class="bg-highlight">World</mark>'
 * // result.hasMatch: true
 * // result.matchCount: 1
 * ```
 */
export function highlightText(
  text: string,
  query: string,
  highlightClass: string = 'bg-highlight'
): HighlightResult {
  // Handle empty or whitespace-only query
  if (!query || query.trim() === '') {
    return {
      html: escapeHtml(text),
      hasMatch: false,
      matchCount: 0,
    };
  }

  // Handle empty text
  if (!text) {
    return {
      html: '',
      hasMatch: false,
      matchCount: 0,
    };
  }

  // First escape the query for HTML to match escaped text
  const escapedQuery = escapeHtml(query);

  // Escape the text first (XSS prevention)
  const escapedText = escapeHtml(text);

  // Create case-insensitive regex for the escaped query
  const regex = new RegExp(`(${escapeRegex(escapedQuery)})`, 'gi');

  // Count matches
  const matches = escapedText.match(regex);
  const matchCount = matches ? matches.length : 0;

  if (matchCount === 0) {
    return {
      html: escapedText,
      hasMatch: false,
      matchCount: 0,
    };
  }

  // Replace matches with highlighted version
  const html = escapedText.replace(
    regex,
    `<mark class="${highlightClass}">$1</mark>`
  );

  return {
    html,
    hasMatch: true,
    matchCount,
  };
}
