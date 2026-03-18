import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import applications, auth, companies, interviews

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # scheduler.start() added in chunk 9
    yield
    # scheduler.shutdown(wait=False) added in chunk 9


app = FastAPI(title="job-tracker-v2", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(applications.router)
app.include_router(interviews.router)

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
