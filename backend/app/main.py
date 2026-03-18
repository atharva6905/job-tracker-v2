import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # scheduler.start() added in chunk 9
    yield
    # scheduler.shutdown(wait=False) added in chunk 9


app = FastAPI(title="job-tracker-v2", lifespan=lifespan)

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
extension_origin = os.getenv("EXTENSION_ORIGIN", "")
if extension_origin:
    origins.append(extension_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}
