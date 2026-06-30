from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..services.datasets import get_dataset, import_dataset, list_datasets


router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
def datasets() -> list[dict]:
    return list_datasets()


@router.get("/{dataset_id}")
def dataset(dataset_id: int) -> dict:
    try:
        return get_dataset(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/upload", status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    description: str = Form(default=""),
) -> dict:
    try:
        return await import_dataset(file, name, description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

