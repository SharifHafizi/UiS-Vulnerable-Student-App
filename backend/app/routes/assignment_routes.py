
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.database import run_query
from app.auth import get_user_from_session

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
UPLOAD_DIR = Path("app/uploads").resolve()


@router.get("/assignments", response_class=HTMLResponse)
def assignments(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    assignment_rows = run_query(
        "SELECT * FROM assignments ORDER BY id",
        fetchall=True,
    )

    submissions = run_query(
        """
        SELECT * FROM submissions
        WHERE user_id=%s
        ORDER BY submitted_at DESC
        """,
        (user["id"],),
        fetchall=True,
    )

    return templates.TemplateResponse(
        "assignments.html",
        {
            "request": request,
            "user": user,
            "assignments": assignment_rows,
            "submissions": submissions,
        },
    )


@router.post("/assignments/upload")
def upload_assignment(
    request: Request,
    assignment_id: int = Form(...),
    file: UploadFile = File(...),
):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Remove directory components from the supplied filename.
    original_name = Path(
        (file.filename or "").replace("\\", "/")
    ).name

    if not original_name or original_name in (".", ".."):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename",
        )

    # Generate a unique server-controlled storage filename.
    stored_filename = (
        f"{user['id']}_{assignment_id}_{uuid4().hex}"
    )

    path = UPLOAD_DIR / stored_filename

    with path.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            out.write(chunk)

    run_query(
        """
        INSERT INTO submissions
            (assignment_id, user_id, filename, file_path, notes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            assignment_id,
            user["id"],
            original_name,
            stored_filename,
            "Uploaded through portal",
        ),
        commit=True,
    )

    return RedirectResponse(
        "/assignments",
        status_code=302,
    )


@router.get("/uploads/{filename}")
def get_upload(request: Request, filename: str):
    user = get_user_from_session(request)

    if not user:
        return RedirectResponse("/login", status_code=302)

    # Only allow a file belonging to the current user.
    submission = run_query(
        """
        SELECT id, filename
        FROM submissions
        WHERE file_path=%s AND user_id=%s
        LIMIT 1
        """,
        (filename, user["id"]),
        fetchone=True,
    )

    if not submission:
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    # Prevent access outside the upload directory.
    path = (UPLOAD_DIR / filename).resolve()

    if path.parent != UPLOAD_DIR or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    return FileResponse(
    path,
    filename=submission["filename"],
    content_disposition_type="attachment",
)
