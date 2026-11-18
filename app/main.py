
import os
import io
import math
import html
import sqlite3
import secrets
import ipaddress
import asyncio

from pathlib import Path
from urllib.parse import urlparse
from functools import lru_cache

import requests
from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    Request,
    Form,
    HTTPException,
    BackgroundTasks,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from app.database import get_connection, initialize_database
from app.auth import (
    hash_password,
    verify_password,
    validate_registration,
)


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SESSION_SECRET = os.getenv("SESSION_SECRET")

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is missing from .env")

COOKIE_HTTPS_ONLY = (
    os.getenv("COOKIE_HTTPS_ONLY", "false").lower() == "true"
)

IP_LOOKUP_ENABLED = (
    os.getenv("IP_LOOKUP_ENABLED", "true").lower() == "true"
)

app = FastAPI(title="GeoTrace")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="geotrace_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=COOKIE_HTTPS_ONLY,
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

initialize_database()


# =========================================================
# DATABASE MIGRATIONS
# =========================================================

def ensure_visit_columns():
    columns = {
        "ip_address": "TEXT",
        "isp": "TEXT",
        "country": "TEXT",
        "region": "TEXT",
        "city": "TEXT",
        "user_agent": "TEXT",
        "consented": "INTEGER DEFAULT 0",
        "ip_consented": "INTEGER DEFAULT 0",
        "gps_consented": "INTEGER DEFAULT 0",
        "latitude": "REAL",
        "longitude": "REAL",
        "altitude": "REAL",
        "accuracy": "REAL",
        "altitude_accuracy": "REAL",
        "heading": "REAL",
        "speed": "REAL",
        "location_status": "TEXT",
        "location_timestamp": "INTEGER",
    }

    with get_connection() as conn:
        existing = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(visits)"
            ).fetchall()
        }

        for name, definition in columns.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE visits ADD COLUMN {name} {definition}"
                )

        conn.commit()


ensure_visit_columns()


# =========================================================
# AUTHENTICATION
# =========================================================

def current_user(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        return None

    with get_connection() as conn:
        user = conn.execute(
            """
            SELECT id, username, email
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    if not user:
        request.session.clear()

    return user


def owned_link(code, user_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM links
            WHERE code = ? AND owner_id = ?
            """,
            (code, user_id),
        ).fetchone()


def owned_visit(visit_id, user_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT visits.*
            FROM visits
            JOIN links ON visits.link_code = links.code
            WHERE visits.id = ? AND links.owner_id = ?
            """,
            (visit_id, user_id),
        ).fetchone()


def get_link(code):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM links WHERE code = ?",
            (code,),
        ).fetchone()


# =========================================================
# PUBLIC IP
# =========================================================

def get_public_client_ip(request: Request):
    """
    Use request.client.host after configuring Uvicorn to trust
    only the local ngrok agent connection.

    Do not read arbitrary X-Forwarded-For values inside this
    function. Uvicorn's proxy middleware processes forwarded
    headers only from configured trusted proxy addresses.
    """

    if not request.client:
        return None

    candidate = request.client.host

    try:
        address = ipaddress.ip_address(candidate)

        if address.is_global:
            return str(address)

    except ValueError:
        pass

    return None


# =========================================================
# ISP / IP METADATA LOOKUP
# =========================================================

@lru_cache(maxsize=2048)
def lookup_ip_metadata(public_ip):
    empty = {
        "isp": None,
        "country": None,
        "region": None,
        "city": None,
    }

    if not public_ip or not IP_LOOKUP_ENABLED:
        return empty

    try:
        response = requests.get(
            f"https://ipwho.is/{public_ip}",
            timeout=5,
            headers={"User-Agent": "GeoTrace/1.0"},
        )
        response.raise_for_status()

        data = response.json()

        if data.get("success") is not True:
            return empty

        connection = data.get("connection") or {}

        return {
            "isp": connection.get("isp"),
            "country": data.get("country"),
            "region": data.get("region"),
            "city": data.get("city"),
        }

    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ):
        return empty


def update_visit_metadata(visit_id, public_ip):
    """
    Runs after the visitor record has been saved.
    The visitor does not need to wait for the ISP lookup.
    """

    metadata = lookup_ip_metadata(public_ip)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE visits
            SET isp = ?, country = ?, region = ?, city = ?
            WHERE id = ?
            """,
            (
                metadata["isp"],
                metadata["country"],
                metadata["region"],
                metadata["city"],
                visit_id,
            ),
        )
        conn.commit()


# =========================================================
# VALIDATION
# =========================================================

def valid_number(value, minimum=None, maximum=None):
    if value is None:
        return None

    if isinstance(value, bool):
        raise ValueError("Invalid number")

    number = float(value)

    if not math.isfinite(number):
        raise ValueError("Invalid number")

    if minimum is not None and number < minimum:
        raise ValueError("Value too small")

    if maximum is not None and number > maximum:
        raise ValueError("Value too large")

    return number


def validate_destination(destination):
    parsed = urlparse(destination)

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise HTTPException(
            status_code=400,
            detail="Enter a valid HTTP or HTTPS URL.",
        )

    return destination


# =========================================================
# REGISTER
# =========================================================

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": None},
    )


@app.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    if current_user(request):
        return RedirectResponse("/", status_code=303)

    error = validate_registration(username, email, password)

    if error:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": error},
            status_code=400,
        )

    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Passwords do not match."},
            status_code=400,
        )

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES (?, ?, ?)
                """,
                (
                    username.strip(),
                    email.strip().lower(),
                    hash_password(password),
                ),
            )
            conn.commit()

    except sqlite3.IntegrityError:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "error": "Username or email is already registered."
            },
            status_code=400,
        )

    return RedirectResponse("/login?registered=1", status_code=303)


# =========================================================
# LOGIN
# =========================================================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    identity: str = Form(...),
    password: str = Form(...),
):
    if current_user(request):
        return RedirectResponse("/", status_code=303)

    identity = identity.strip()

    with get_connection() as conn:
        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ? COLLATE NOCASE
               OR email = ? COLLATE NOCASE
            """,
            (identity, identity),
        ).fetchone()

    if not user or not verify_password(
        password,
        user["password_hash"],
    ):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Invalid username/email or password."
            },
            status_code=401,
        )

    request.session.clear()
    request.session["user_id"] = user["id"]

    return RedirectResponse("/", status_code=303)


# =========================================================
# LOGOUT
# =========================================================

@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# =========================================================
# PDF EXPORT
# =========================================================

def safe_pdf_text(value):
    if value is None or value == "":
        return "Not available"

    return html.escape(str(value))


def create_visit_pdf(records, title="GeoTrace Visit Records"):
    buffer = io.BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "GeoTraceTitle",
        parent=styles["Title"],
        fontSize=19,
        leading=24,
        textColor=colors.HexColor("#172554"),
    )

    normal_style = ParagraphStyle(
        "GeoTraceNormal",
        parent=styles["BodyText"],
        fontSize=8,
        leading=11,
        wordWrap="CJK",
    )

    story = []

    fields = [
        ("Record ID", "id"),
        ("Link Code", "link_code"),
        ("Public IP", "ip_address"),
        ("ISP / Provider", "isp"),
        ("Country", "country"),
        ("Region", "region"),
        ("City", "city"),
        ("User Agent", "user_agent"),
        ("IP Consent", "ip_consented"),
        ("GPS Consent", "gps_consented"),
        ("Location Status", "location_status"),
        ("Latitude", "latitude"),
        ("Longitude", "longitude"),
        ("Altitude", "altitude"),
        ("GPS Accuracy", "accuracy"),
        ("Altitude Accuracy", "altitude_accuracy"),
        ("Heading", "heading"),
        ("Speed", "speed"),
        ("Location Timestamp", "location_timestamp"),
        ("Visit Date", "visited_at"),
    ]

    for index, record in enumerate(records):
        if index:
            story.append(PageBreak())

        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 8))

        story.append(
            Paragraph(
                f"Visit Record #{record['id']}",
                styles["Heading2"],
            )
        )

        rows = [
            [
                Paragraph("<b>Field</b>", normal_style),
                Paragraph("<b>Value</b>", normal_style),
            ]
        ]

        for label, key in fields:
            rows.append([
                Paragraph(safe_pdf_text(label), normal_style),
                Paragraph(safe_pdf_text(record[key]), normal_style),
            ])

        table = Table(
            rows,
            colWidths=[55 * mm, 115 * mm],
            repeatRows=1,
        )

        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0),
                 colors.HexColor("#e0e7ff")),
                ("GRID", (0, 0), (-1, -1), 0.4,
                 colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ])
        )

        story.append(table)

    if not records:
        story.append(
            Paragraph("No visit records are available.", normal_style)
        )

    document.build(story)
    buffer.seek(0)
    return buffer


def pdf_response(records, filename, title):
    return StreamingResponse(
        create_visit_pdf(records, title),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, page: int = 1):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    page_size = 10
    page = max(1, page)

    with get_connection() as conn:
        links = conn.execute(
            """
            SELECT *
            FROM links
            WHERE owner_id = ?
            ORDER BY id DESC
            """,
            (user["id"],),
        ).fetchall()

        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM visits
            JOIN links ON visits.link_code = links.code
            WHERE links.owner_id = ?
            """,
            (user["id"],),
        ).fetchone()[0]

        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size

        visits = conn.execute(
            """
            SELECT visits.*
            FROM visits
            JOIN links ON visits.link_code = links.code
            WHERE links.owner_id = ?
            ORDER BY visits.id DESC
            LIMIT ? OFFSET ?
            """,
            (user["id"], page_size, offset),
        ).fetchall()

        consented = conn.execute(
            """
            SELECT COUNT(*)
            FROM visits
            JOIN links ON visits.link_code = links.code
            WHERE links.owner_id = ?
              AND visits.consented = 1
            """,
            (user["id"],),
        ).fetchone()[0]

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "links": links,
            "visits": visits,
            "total": total,
            "consented": consented,
            "page": page,
            "total_pages": total_pages,
            "page_size": page_size,
            "user": user,
        },
    )


# =========================================================
# CREATE LINK
# =========================================================

@app.post("/create")
def create_link(
    request: Request,
    destination: str = Form(...),
):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    destination = validate_destination(destination.strip())
    code = secrets.token_urlsafe(8)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO links (code, destination, owner_id)
            VALUES (?, ?, ?)
            """,
            (code, destination, user["id"]),
        )
        conn.commit()

    return RedirectResponse("/#tracking-links", status_code=303)


# =========================================================
# DELETE LINK
# =========================================================

@app.post("/links/{code}/delete")
def delete_link(request: Request, code: str):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    with get_connection() as conn:
        link = conn.execute(
            """
            SELECT id FROM links
            WHERE code = ? AND owner_id = ?
            """,
            (code, user["id"]),
        ).fetchone()

        if not link:
            raise HTTPException(status_code=404, detail="Not found")

        conn.execute(
            "DELETE FROM visits WHERE link_code = ?",
            (code,),
        )
        conn.execute(
            "DELETE FROM links WHERE code = ? AND owner_id = ?",
            (code, user["id"]),
        )
        conn.commit()

    return RedirectResponse("/#tracking-links", status_code=303)


# =========================================================
# PUBLIC VISITOR PAGE
# =========================================================

@app.get("/visit/{code}", response_class=HTMLResponse)
def visit_page(request: Request, code: str):
    link = get_link(code)

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    return templates.TemplateResponse(
        request=request,
        name="visitor.html",
        context={"link": link},
    )


# =========================================================
# SAVE CONSENTED VISITOR INFORMATION
# =========================================================

@app.post("/visit/{code}/location")
async def save_location(
    request: Request,
    code: str,
    background_tasks: BackgroundTasks,
):
    link = get_link(code)

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    try:
        data = await request.json()

        if not isinstance(data, dict):
            raise ValueError("Invalid request")

        ip_consent = data.get("ip_consent") is True
        gps_consent = data.get("gps_consent") is True

        # At least one collection choice must be explicitly accepted.
        if not ip_consent and not gps_consent:
            return JSONResponse(
                {"error": "No collection consent was provided."},
                status_code=403,
            )

        latitude = longitude = None
        altitude = accuracy = None
        altitude_accuracy = heading = speed = None
        timestamp = None

        if gps_consent:
            latitude = valid_number(data.get("latitude"), -90, 90)
            longitude = valid_number(data.get("longitude"), -180, 180)
            accuracy = valid_number(data.get("accuracy"), 0)
            altitude = valid_number(data.get("altitude"))
            altitude_accuracy = valid_number(
                data.get("altitude_accuracy"), 0
            )
            heading = valid_number(data.get("heading"), 0, 360)
            speed = valid_number(data.get("speed"), 0)

            timestamp = data.get("timestamp")

            if (
                latitude is None
                or longitude is None
                or accuracy is None
                or isinstance(timestamp, bool)
                or not isinstance(timestamp, (int, float))
                or timestamp < 0
            ):
                raise ValueError("Incomplete GPS data")

            timestamp = int(timestamp)

    except (ValueError, TypeError, AttributeError):
        return JSONResponse(
            {"error": "Invalid visitor information."},
            status_code=400,
        )

    # IP is only obtained and saved if IP collection was accepted.
    public_ip = get_public_client_ip(request) if ip_consent else None

    user_agent = request.headers.get("user-agent", "")

    location_status = "granted" if gps_consent else "declined"

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO visits (
                link_code,
                ip_address,
                user_agent,
                consented,
                ip_consented,
                gps_consented,
                latitude,
                longitude,
                altitude,
                accuracy,
                altitude_accuracy,
                heading,
                speed,
                location_status,
                location_timestamp
            )
            VALUES (
                ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                code,
                public_ip,
                user_agent,
                int(ip_consent),
                int(gps_consent),
                latitude,
                longitude,
                altitude,
                accuracy,
                altitude_accuracy,
                heading,
                speed,
                location_status,
                timestamp,
            ),
        )

        visit_id = cursor.lastrowid
        conn.commit()

    # ISP and approximate region lookup happens after saving.
    if ip_consent and public_ip:
        background_tasks.add_task(
            update_visit_metadata,
            visit_id,
            public_ip,
        )

    return JSONResponse({
        "success": True,
        "redirect_url": link["destination"],
    })


# =========================================================
# DECLINE COLLECTION
# =========================================================

@app.post("/visit/{code}/decline")
def decline_visit(code: str):
    link = get_link(code)

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    # No visit record is created when all collection is declined.
    return RedirectResponse(link["destination"], status_code=303)


# =========================================================
# VIEW VISIT
# =========================================================

@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def view_visit(request: Request, visit_id: int):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    visit = owned_visit(visit_id, user["id"])

    if not visit:
        raise HTTPException(status_code=404, detail="Not found")

    return templates.TemplateResponse(
        request=request,
        name="visit_detail.html",
        context={"visit": visit, "user": user},
    )


# =========================================================
# DELETE ONE VISIT
# =========================================================

@app.post("/visits/{visit_id}/delete")
def delete_visit(request: Request, visit_id: int):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM visits
            WHERE id = ?
              AND link_code IN (
                  SELECT code FROM links WHERE owner_id = ?
              )
            """,
            (visit_id, user["id"]),
        )
        conn.commit()

    return RedirectResponse("/#visits", status_code=303)


# =========================================================
# BULK DELETE
# =========================================================

@app.post("/visits/delete-selected")
def delete_selected_visits(
    request: Request,
    visit_ids: list[int] = Form(default=[]),
):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    selected_ids = list(set(visit_ids))

    if selected_ids:
        placeholders = ",".join("?" for _ in selected_ids)

        with get_connection() as conn:
            conn.execute(
                f"""
                DELETE FROM visits
                WHERE id IN ({placeholders})
                  AND link_code IN (
                      SELECT code FROM links WHERE owner_id = ?
                  )
                """,
                (*selected_ids, user["id"]),
            )
            conn.commit()

    return RedirectResponse("/#visits", status_code=303)


# =========================================================
# EXPORT ONE VISIT
# =========================================================

@app.get("/visits/{visit_id}/export.pdf")
def export_one_visit(request: Request, visit_id: int):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    visit = owned_visit(visit_id, user["id"])

    if not visit:
        raise HTTPException(status_code=404, detail="Not found")

    return pdf_response(
        [visit],
        f"geotrace_visit_{visit_id}.pdf",
        "GeoTrace Visit Report",
    )


# =========================================================
# EXPORT ALL VISITS
# =========================================================

@app.get("/visits/export.pdf")
def export_all_visits(request: Request):
    user = current_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    with get_connection() as conn:
        visits = conn.execute(
            """
            SELECT visits.*
            FROM visits
            JOIN links ON visits.link_code = links.code
            WHERE links.owner_id = ?
            ORDER BY visits.id DESC
            """,
            (user["id"],),
        ).fetchall()

    return pdf_response(
        visits,
        "geotrace_all_records.pdf",
        "GeoTrace Visit Report",
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
def health_check():
    return {
        "status": "running",
        "application": "GeoTrace",
        "database": "SQLite",
        "ip_lookup_enabled": IP_LOOKUP_ENABLED,
    }
