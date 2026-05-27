from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import AccountSummary, Brief
from .store import list_accounts, read_brief

app = FastAPI(title="QBR Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/accounts", response_model=list[AccountSummary])
def get_accounts() -> list[AccountSummary]:
    # The problem is: the left pane needs to list which accounts exist and their run
    # status so the user can pick one.
    # The way we solve this is: scan output/ for per-account brief.json files and
    # project them into AccountSummary records.
    # flow: UI mounts -> AccountList.useEffect -> GET /accounts -> get_accounts() <-- HERE
    return list_accounts()


@app.post("/accounts/{account_id}/run", response_model=Brief)
def run_account(account_id: str) -> Brief:
    # The problem is: clicking Run needs to trigger the pipeline and block until the
    # brief is ready for render.
    # The way we solve this is: scaffold returns the existing fixture; once the
    # LangGraph pipeline lands this will invoke it synchronously and write the result.
    # flow: UI Run button -> RunButton.onClick -> POST /run -> run_account() <-- HERE
    # TODO: replace stub with graph.run(account_id) once src/graph.py exists
    try:
        return read_brief(account_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")


@app.get("/accounts/{account_id}/brief", response_model=Brief)
def get_brief(account_id: str) -> Brief:
    # The problem is: re-opening an already-run account in the UI needs to hydrate
    # the results pane without re-running the pipeline.
    # The way we solve this is: read brief.json from disk and validate it against the
    # schema before returning, so the UI is guaranteed a well-formed payload.
    # flow: UI account-select -> ResultsPane.useEffect -> GET /brief -> get_brief() <-- HERE
    try:
        return read_brief(account_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No brief found for '{account_id}'")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=True)
