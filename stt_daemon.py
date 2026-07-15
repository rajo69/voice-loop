"""
Backwards-compatible entry point. The daemon now runs both input (STT) and
output (readback) together -- see voiced.py. This shim just launches it.
"""
from voiced import main

if __name__ == "__main__":
    main()
