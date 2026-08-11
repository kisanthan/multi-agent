"""The one tool that is not an AI agent: the document reader.

`reader.py` turns a PDF into markdown and enforces the Least-Privilege AD
check at the point of first access -- before any parsing, model call, or
target-system write happens.
"""
