"""Camera management - every camera the platform watches, and its lifecycle.

``definitions``
    What a camera is: identity, role, coverage, stream address.
``registry``
    Which cameras exist - the environment's declarations plus operator edits.
``topology_store``
    How camera zones connect across the site.
``probe``
    Connection tests and stream diagnosis, without competing for a stream.
``status``
    Turning worker state and measurements into a camera's connection status.
``runtime``
    Everything one camera needs to run: perception, analysis, video, queues.
``manager``
    Owns every runtime and applies operator changes to them while running.

The runtime and manager are imported from their modules directly rather than
re-exported here: they depend on workers and services, and this package's
lightweight modules are imported by those same services.
"""

from __future__ import annotations
