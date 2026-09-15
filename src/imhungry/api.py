"""FastAPI adapters. Resource handlers call services, never Strands tools."""

from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Body, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field, ValidationError

from .auth import deny_authentication
from .errors import AppError
from .models import RECORDS, Strategy, StrategyCalculationRequest, Recipe, FoodEstimateRequest, Conversation, Model
from .providers import run_async


def create_app(services, *, verifier=deny_authentication, conversations=None, cors_origins=()):
    app = FastAPI(title="ImHungry", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services
    app.state.conversations = conversations

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            # Keep sanitized failures inside the CORS and request-ID boundary.
            response = await unavailable(request, exc)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    def error_response(request, code, message, status, details=None):
        body = {"code": code, "message": message, "request_id": getattr(request.state, "request_id", str(uuid4()))}
        if details:
            body["details"] = details
        return JSONResponse(body, status_code=status)

    @app.exception_handler(AppError)
    async def domain_error(request, exc):
        return error_response(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return error_response(request, "validation", "Request validation failed", 422,
                              [{"field": list(e["loc"]), "type": e["type"]} for e in exc.errors()])

    @app.exception_handler(Exception)
    async def unavailable(request, exc):
        return error_response(request, "service_unavailable", "Unable to complete the request", 503)

    def identity(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "):
            raise AppError("unauthorized", "A valid Cognito access token is required", 401)
        return verifier(authorization[7:])

    def version(if_match: Annotated[str, Header()]):
        value = if_match.strip('"')
        if not value.isdigit():
            raise AppError("validation", "If-Match must contain a non-negative integer version")
        return int(value)

    def request_key(idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
        return idempotency_key

    app.state.identity_dependency = identity
    app.state.version_dependency = version
    app.state.request_key_dependency = request_key

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/profile")
    def profile(user=Depends(identity)):
        return services.get(user, "profile")

    @app.patch("/v1/profile")
    def update_profile(patch: dict = Body(), expected=Depends(version), user=Depends(identity)):
        return services.update(user, "profile", "profile", patch, expected)

    @app.post("/v1/nutrition-strategies/calculate")
    def calculate(request: StrategyCalculationRequest, user=Depends(identity)):
        return services.calculate_strategy(user, request.data())

    @app.post("/v1/nutrition-strategies", status_code=201)
    def strategy(request: Strategy, key=Depends(request_key), user=Depends(identity)):
        return services.create(user, "nutrition-strategies", request.data(), key)

    @app.get("/v1/nutrition-strategies/current")
    def current(on_date: date | None = None, user=Depends(identity)):
        return {"strategy": services.current_strategy(user, on_date)}

    @app.get("/v1/nutrition-strategies")
    def history(start_date: date | None = None, end_date: date | None = None, limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=Depends(identity)):
        return services.list(user, "nutrition-strategies", start_date, end_date, limit=limit, cursor=cursor)

    @app.get("/v1/nutrition-summary")
    def summary(start_date: date, end_date: date | None = None, user=Depends(identity)):
        return services.summary(user, start_date, end_date)

    def resource_routes(kind):
        def create(body: dict, key=Depends(request_key), user=Depends(identity)):
            return services.create(user, kind, body.data(), key)
        create.__annotations__["body"] = RECORDS[kind][1]

        def collection(start_date: date | None = None, end_date: date | None = None,
                       query: str | None = Query(None, max_length=200), status: str | None = None,
                       category: str | None = None, limit: int = Query(50, ge=1, le=100),
                       cursor: str | None = Query(None, max_length=2000), user=Depends(identity)):
            return services.list(user, kind, start_date, end_date, query=query, status=status, category=category, limit=limit, cursor=cursor)

        def get(reference: str, user=Depends(identity)):
            return services.get(user, kind, reference)

        def patch(reference: str, body: dict = Body(), expected=Depends(version), user=Depends(identity)):
            return services.update(user, kind, reference, body, expected)

        def delete(reference: str, expected=Depends(version), user=Depends(identity)):
            return services.delete(user, kind, reference, expected)

        path = "/v1/" + kind
        for method, suffix, endpoint, status_code in [("POST", "", create, 201), ("GET", "", collection, 200),
                ("GET", "/{reference}", get, 200), ("PATCH", "/{reference}", patch, 200), ("DELETE", "/{reference}", delete, 200)]:
            app.add_api_route(path + suffix, endpoint, methods=[method], status_code=status_code, name=f"{method}_{kind}")

    @app.post("/v1/recipes/calculate")
    def recipe_calculation(request: Recipe, user=Depends(identity)):
        return services.calculate_recipe(request.data())

    @app.get("/v1/hydration-summary")
    def hydration_summary(start_date: date, end_date: date | None = None, user=Depends(identity)):
        return services.hydration_summary(user, start_date, end_date)

    @app.get("/v1/progress-summary")
    def progress_summary(start_date: date, end_date: date, user=Depends(identity)):
        return services.progress(user, start_date, end_date)

    @app.get("/v1/foods/frequent")
    def frequent(query: str | None = None, lookback_days: int = Query(60, ge=1, le=366), user=Depends(identity)):
        return {"items": services.frequent_foods(user, query, lookback_days)}

    @app.get("/v1/foods/search")
    def search(query: str, brand: str | None = None, restaurant: str | None = None, serving: str | None = None, user=Depends(identity)):
        return services.lookup_food(user, {"query": query, "brand": brand, "restaurant": restaurant, "serving": serving})

    @app.post("/v1/foods/estimate")
    def estimate(request: FoodEstimateRequest, user=Depends(identity)):
        return services.estimate_food(user, request.data())

    @app.get("/v1/restaurant-menus/search")
    def menu(restaurant_name: str, location: str | None = None, query: str | None = None, menu_url: str | None = None, user=Depends(identity)):
        return services.restaurant_menu(user, restaurant_name, location, query, menu_url)

    for kind in ("food-log", "recipes", "saved-foods", "hydration", "planned-meals", "check-ins", "behavior-patterns"):
        resource_routes(kind)

    def conversation_service():
        if conversations is None:
            raise AppError("service_unavailable", "Conversation storage is not configured", 503)
        return conversations

    class Message(Model):
        message: Annotated[str, Field(min_length=1, max_length=12000)]
        client_request_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None

    @app.post("/v1/conversations", status_code=201)
    def create_conversation(request: Conversation, key=Depends(request_key), user=Depends(identity), conv=Depends(conversation_service)):
        return conv.create(user, request.data(), key)

    @app.get("/v1/conversations")
    def list_conversations(limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=Depends(identity)):
        return services.list(user, "conversations", limit=limit, cursor=cursor)

    @app.get("/v1/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, user=Depends(identity), conv=Depends(conversation_service)):
        return conv.get(user, conversation_id)

    @app.patch("/v1/conversations/{conversation_id}")
    def patch_conversation(conversation_id: str, patch: dict = Body(), expected=Depends(version), user=Depends(identity), conv=Depends(conversation_service)):
        return conv.update(user, conversation_id, patch, expected)

    @app.delete("/v1/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, expected=Depends(version), user=Depends(identity), conv=Depends(conversation_service)):
        return run_async(lambda: conv.delete(user, conversation_id, expected))

    @app.get("/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, user=Depends(identity), conv=Depends(conversation_service)):
        return run_async(lambda: conv.messages(user, conversation_id))

    @app.post("/v1/conversations/{conversation_id}/messages")
    def send_message(conversation_id: str, request: Message,
                           idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
                           user=Depends(identity), conv=Depends(conversation_service)):
        if idempotency_key and request.client_request_id and idempotency_key != request.client_request_id:
            raise AppError("validation", "Header and body request IDs must match")
        return run_async(lambda: conv.invoke(user, conversation_id, request.message, idempotency_key or request.client_request_id))
    if cors_origins:
        # Last registered is outermost, including middleware-generated failures.
        app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins),
                           allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                           allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match"],
                           expose_headers=["X-Request-ID"], max_age=600)
    return app
