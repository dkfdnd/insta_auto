"""Internal Studio responsibilities; import the public facade from hotpost.studio.

Commands modify state, media projects it for the UI, lifecycle owns queue
completion, and generation/editing steps execute external work. None starts
workers or opens a database on import.
"""
