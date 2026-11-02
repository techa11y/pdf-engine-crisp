"""What WeasyPrint may load while rendering the /build HTML.

/build renders caller-supplied HTML. With WeasyPrint's default fetcher that HTML can make
the engine read any local file or URL: ``<link rel="attachment" href="file:///...">``
embeds the file inside the returned PDF (verified locally on WeasyPrint 62.3 and 70.0),
and ``<img src="http://...">`` makes the engine issue requests to arbitrary hosts. The
endpoints are unauthenticated, so that is a local-file disclosure (the container
environment holds the Supabase service key) and a server-side request forgery path.

Real documents need neither: in the 60 days to 2026-11-02 none of 17,871 production page
HTMLs referenced an http, file or data resource (every <img> had an empty src), and the
worker adds no images, links or stylesheets at compile time. The only resources the
engine itself references are ``data:`` URIs (the transparent link-overlay GIF) and the
per-request JPEGs it writes for the visual pages. This fetcher allows exactly those and
refuses everything else before any file or network access; WeasyPrint then logs a
warning and renders without the resource.
"""
import os
from urllib.parse import unquote, urlparse

from weasyprint.urls import URLFetcher


class RestrictedURLFetcher(URLFetcher):
    """URLFetcher that serves ``data:`` URIs and an explicit allow-list of local files only."""

    def __init__(self, allowed_files=(), **kwargs):
        super().__init__(**kwargs)
        self._allowed_files = {os.path.realpath(p) for p in allowed_files}

    def fetch(self, url, headers=None):
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme == "data":
            return super().fetch(url, headers)
        if scheme == "file":
            path = os.path.realpath(unquote(urlparse(url).path))
            if path in self._allowed_files:
                return super().fetch(url, headers)
        raise ValueError(f"resource blocked by engine policy: {url[:120]}")
