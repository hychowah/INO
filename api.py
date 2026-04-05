#!/usr/bin/env python3
"""
Thin entry point — run directly with: python api.py
For import (uvicorn api:app) the api/ package is used automatically.
"""

if __name__ == "__main__":
    import logging

    import uvicorn

    import config

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    uvicorn.run(
        "api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
    )
