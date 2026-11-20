/**
 * Turns a title into a URL slug.
 * Lowercases the text, replaces each run of characters that are not letters or digits
 * with one hyphen, and removes a leading or trailing hyphen.
 * An empty title gives an empty slug.
 */
export function slugify(title) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
