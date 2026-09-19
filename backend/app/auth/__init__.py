"""Operator authentication.

Who is at the console, and whether they may change what they are trying to
change. Sign-in state lives in the database; the browser holds only a random
session token in an HttpOnly cookie, which also reaches the Command Center
socket and the video streams - places a bearer header cannot.
"""
