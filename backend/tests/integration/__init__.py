"""Integration tests for the backend.

The application assembled by its own composition root, driven through its HTTP
surface. Still no camera and no GPU: the pipeline is disabled and perception
state is populated directly, because what is under test is the API contract
rather than the model behind it.
"""
