"""Route registration — includes all API routers into the FastAPI app."""

from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    """Include every route module into *app*."""
    from api.routes import chat, concepts, graph, misc, pages, relations, reviews, topics

    app.include_router(pages.router)
    app.include_router(chat.router)
    app.include_router(topics.router)
    app.include_router(concepts.router)
    app.include_router(relations.router)
    app.include_router(reviews.router)
    app.include_router(graph.router)
    app.include_router(misc.router)
