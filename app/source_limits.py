"""Bounded budgets for public website attachments, separate from manual upload."""

# The public source reader retains the entire original, never a truncated file.
# These limits are deliberately separate from the existing manual upload limits.
MAX_SOURCE_FILE = 100 * 1024 * 1024
MAX_SOURCE_BYTES = 150 * 1024 * 1024
MAX_SOURCE_CHARS = 200_000
MAX_SOURCE_FILES = 20
MAX_SOURCE_MATERIALS = 24
MAX_SOURCE_PAGES = 300
SOURCE_ATTACHMENT_SECONDS = 240
