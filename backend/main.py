import backend.config  # noqa: F401 – must be first to set sys.path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import recommendations, reminders, agent, llm, comms, market

app = FastAPI(title="FinPulse API", version="1.0.0", description="Financial advisor calendar backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For demo, allow all. Update with your frontend URL later for security.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommendations.router, prefix="/api/recommendations", tags=["Recommendations"])
app.include_router(reminders.router, prefix="/api/reminders", tags=["Reminders"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
app.include_router(comms.router, prefix="/api/comms", tags=["Communications"])
app.include_router(market.router, prefix="/api/market", tags=["Market"])


@app.get("/")
def root():
    return {"status": "FinPulse API running", "docs": "/docs"}
