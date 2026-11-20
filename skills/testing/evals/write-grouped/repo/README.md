# Fixture

`slugify(title)` in `src/slug.js` turns a title into a URL slug.

- It lowercases the text.
- It replaces each run of characters that are not letters or digits with one hyphen.
- It removes a leading or trailing hyphen.
- An empty title gives an empty slug.
