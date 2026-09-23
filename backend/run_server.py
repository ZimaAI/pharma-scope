#!/usr/bin/env python3
"""PharmaScope Lite API startup script.

Use ``PHARMA_LEGACY=1`` only when running the original GPT Researcher demo
routes.  The default is the versioned PharmaScope API in
``pharma_scope_app``.
"""

import uvicorn
import os
import sys

# Add the backend directory to Python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(backend_dir))

if __name__ == "__main__":
    # Change to backend directory
    os.chdir(os.path.dirname(backend_dir))

    # Start the server
    app_module = "backend.server.app:app" if os.getenv("PHARMA_LEGACY") == "1" else "backend.pharma_scope_app:app"
    uvicorn.run(
        app_module,
        host=os.getenv("PHARMA_BIND_HOST", "127.0.0.1"),
        port=8000,
        reload=True,
        log_level="info"
    )


