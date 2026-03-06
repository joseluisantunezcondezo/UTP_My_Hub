import base64
import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, parse, request
from urllib.parse import urlparse

import streamlit as st


# ======================================================
# CONFIGURACION
# ======================================================

st.set_page_config(
    page_title="Central Hub | Plataforma UTP",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)


@dataclass(frozen=True)
class AppCard:
    title: str
    description: str
    source_file: str
    url: str
    area: str
    icon: str
    accent: str = ""


DEFAULT_APPS: List[AppCard] = [
    AppCard(
        title="UTP - Generación de Documentos Diseña +",
        description="Automatización de documentos (Mapeo, Consignas, Rúbricas, Sesiones) a partir de plantillas.",
        source_file="app.py",
        url="https://plataforma-utpgeneracion-documentos-joseluisantunezcondezo.streamlit.app/",
        area="Products Operations",
        icon="📄",
    ),
    AppCard(
        title="UTP - GrammarScan",
        description="Revisión automatizada de ortografía y gramática en documentos académicos.",
        source_file="app.py",
        url="https://utpgrammarscan-joseluisantunezcondezo.streamlit.app/",
        area="Products Operations",
        icon="✅",
    ),
    AppCard(
        title="UTP - Broken Link Checker",
        description="Validación y monitoreo de enlaces rotos contenidos en documentos académicos.",
        source_file="app.py",
        url="https://utp-broken-link-checker-joseluisantunezcondezo.streamlit.app/",
        area="Products Operations",
        icon="🔗",
    ),
    AppCard(
        title="UTP - Syllabus to Excel Transformation",
        description="Convierte múltiples archivos de silabos en formato Word a tablas estructuradas de Excel.",
        source_file="app.py",
        url="https://syllabus-excel-transformation-joseluisantunezcondezo.streamlit.app/",
        area="Products Operations",
        icon="📊",
    ),
]

# ======================================================
# ICONOS PNG (LOCALES)
# ======================================================

# Asocia URLs (normalizadas sin "/" final) con archivos PNG del repositorio.
# Coloca estos PNG en la misma carpeta que hub.py o dentro de /assets, /static, /images o /icons.
ICON_PNG_BY_URL: Dict[str, str] = {
    "https://utp-broken-link-checker-joseluisantunezcondezo.streamlit.app": "Broken_Link_Checker.png",
    "https://syllabus-excel-transformation-joseluisantunezcondezo.streamlit.app": "Excel_Transformation.png",
    "https://utpgrammarscan-joseluisantunezcondezo.streamlit.app": "Grammar_Scan.png",
    "https://plataforma-utpgeneracion-documentos-joseluisantunezcondezo.streamlit.app": "Plataforma_UTP_Diseña_+.png",
}

ICON_PNG_SEARCH_DIRS: Tuple[str, ...] = ("", "assets", "static", "images", "icons")


BASE_AREAS = [
    {"name": "Products Operations", "icon": "⚙️"},
    {"name": "Data & Analytics", "icon": "📣"},
]

REGISTRY_FILENAME = "apps_registry.json"
DEFAULT_CUSTOM_SOURCE = REGISTRY_FILENAME
DEFAULT_CUSTOM_ICON = "🧩"
DEFAULT_CUSTOM_AREA_ICON = "🗂️"
DEFAULT_GITHUB_REGISTRY_PATH = "data/apps_registry.json"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


# ======================================================
# MODELOS Y ERRORES DE PERSISTENCIA
# ======================================================


class RegistryError(Exception):
    pass


class RegistryConflictError(RegistryError):
    pass


class DuplicateAppError(RegistryError):
    pass


@dataclass(frozen=True)
class RegistryBackendInfo:
    mode: str
    label: str
    details: str


# ======================================================
# HELPERS GENERALES
# ======================================================


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())



def slugify_key(value: str) -> str:
    """Convierte un texto en un identificador seguro (para keys/CSS)."""
    clean = normalize_text(value).lower()
    clean = re.sub(r"[^a-z0-9]+", "_", clean).strip("_")
    return clean or "x"



def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False




def normalize_url_key(url: str) -> str:
    """Normaliza una URL para mapear iconos (sin slash final y en minúsculas)."""
    return normalize_text(url).rstrip("/").lower()


_CACHE_DATA = getattr(st, "cache_data", None)
if callable(_CACHE_DATA):
    _cache_decorator = _CACHE_DATA(show_spinner=False)
else:
    _cache_decorator = lambda f: f


@_cache_decorator
def load_png_base64(filename: str) -> Optional[str]:
    """Carga un PNG local y lo devuelve en base64 (o None si no existe)."""
    filename = normalize_text(filename)
    if not filename:
        return None

    try:
        base_dir = Path(__file__).resolve().parent
    except NameError:
        base_dir = Path.cwd()

    candidates = []
    for rel in ICON_PNG_SEARCH_DIRS:
        candidates.append(base_dir / rel / filename)
    # Fallback adicional (por si el CWD difiere en despliegue)
    for rel in ICON_PNG_SEARCH_DIRS:
        candidates.append(Path.cwd() / rel / filename)

    for path in candidates:
        try:
            if path.exists() and path.is_file():
                return base64.b64encode(path.read_bytes()).decode("utf-8")

            # Fallback: búsqueda case-insensitive en el directorio (útil en repos con nombres distintos en may/min).
            parent = path.parent
            if parent.exists() and parent.is_dir():
                target = path.name.lower()
                for child in parent.iterdir():
                    try:
                        if child.is_file() and child.name.lower() == target:
                            return base64.b64encode(child.read_bytes()).decode("utf-8")
                    except Exception:
                        continue
        except Exception:
            continue
    return None


def card_icon_markup(app: "AppCard") -> str:
    """Devuelve el HTML del ícono para la tarjeta: PNG (si aplica) o emoji."""
    url_key = normalize_url_key(app.url)
    png_name = ICON_PNG_BY_URL.get(url_key)
    if png_name:
        b64 = load_png_base64(png_name)
        if b64:
            alt = html.escape(app.title, quote=True)
            return f'<img class="hub-card-icon-img" src="data:image/png;base64,{b64}" alt="{alt}" />'
    # Fallback (emoji / texto)
    return html.escape(app.icon)


def appcard_to_record(app: AppCard) -> Dict[str, str]:
    record = asdict(app)
    return {key: (value if isinstance(value, str) else str(value)) for key, value in record.items()}



def record_to_appcard(item: Dict[str, Any]) -> Optional[AppCard]:
    if not isinstance(item, dict):
        return None

    title = normalize_text(str(item.get("title", "")))
    description = normalize_text(str(item.get("description", "")))
    source_file = normalize_text(str(item.get("source_file", DEFAULT_CUSTOM_SOURCE))) or DEFAULT_CUSTOM_SOURCE
    url = normalize_text(str(item.get("url", "")))
    area = normalize_text(str(item.get("area", "")))
    icon = normalize_text(str(item.get("icon", DEFAULT_CUSTOM_ICON))) or DEFAULT_CUSTOM_ICON
    accent = normalize_text(str(item.get("accent", "")))

    if not all([title, description, url, area]) or not is_valid_url(url):
        return None

    return AppCard(
        title=title,
        description=description,
        source_file=source_file,
        url=url,
        area=area,
        icon=icon,
        accent=accent,
    )



def dedupe_apps(apps: List[AppCard]) -> List[AppCard]:
    deduped: List[AppCard] = []
    seen_titles = set()
    seen_urls = set()

    for app in apps:
        title_key = app.title.strip().lower()
        url_key = app.url.strip().lower()
        if title_key in seen_titles or url_key in seen_urls:
            continue
        seen_titles.add(title_key)
        seen_urls.add(url_key)
        deduped.append(app)

    return deduped



def app_exists(apps: List[AppCard], title: str, url: str) -> bool:
    title_key = title.strip().lower()
    url_key = url.strip().lower()
    return any(
        app.title.strip().lower() == title_key or app.url.strip().lower() == url_key
        for app in apps
    )



def app_exists_excluding(
    apps: List[AppCard],
    title: str,
    url: str,
    original_title: str,
    original_url: str,
) -> bool:
    title_key = title.strip().lower()
    url_key = url.strip().lower()
    original_title_key = original_title.strip().lower()
    original_url_key = original_url.strip().lower()

    return any(
        (app.title.strip().lower(), app.url.strip().lower()) != (original_title_key, original_url_key)
        and (app.title.strip().lower() == title_key or app.url.strip().lower() == url_key)
        for app in apps
    )



def format_registry_app_option(app: AppCard) -> str:
    return f"{app.icon} {app.title} — {app.area}"



def get_registry_path() -> Path:
    try:
        return Path(__file__).resolve().with_name(REGISTRY_FILENAME)
    except NameError:
        return Path.cwd() / REGISTRY_FILENAME


REGISTRY_PATH = get_registry_path()


# ======================================================
# BACKEND LOCAL JSON
# ======================================================


class LocalJsonRegistryBackend:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.info = RegistryBackendInfo(
            mode="local_json",
            label="JSON local",
            details=f"Archivo local: {self.path.name}",
        )

    def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                json.dumps({"apps": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _read_raw(self) -> Dict[str, Any]:
        self._ensure_file()
        try:
            raw_data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw_data = {"apps": []}
        if not isinstance(raw_data, dict):
            raw_data = {"apps": []}
        apps = raw_data.get("apps", [])
        if not isinstance(apps, list):
            raw_data["apps"] = []
        return raw_data

    def load_apps(self) -> List[AppCard]:
        raw_data = self._read_raw()
        valid_apps: List[AppCard] = []
        for item in raw_data.get("apps", []):
            app = record_to_appcard(item)
            if app is not None:
                valid_apps.append(app)
        return dedupe_apps(valid_apps)

    def _write_payload(self, raw_apps: List[Dict[str, Any]]) -> None:
        payload = {"apps": raw_apps}
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def append_app(self, app: AppCard) -> None:
        raw_data = self._read_raw()
        current_apps = self.load_apps()
        if app_exists(current_apps, app.title, app.url):
            raise DuplicateAppError("Ya existe una app con el mismo nombre o con la misma URL.")

        raw_apps = raw_data.get("apps", [])
        raw_apps.append(appcard_to_record(app))
        self._write_payload(raw_apps)

    def update_app(self, original_title: str, original_url: str, updated_app: AppCard) -> None:
        raw_data = self._read_raw()
        raw_apps = raw_data.get("apps", [])
        current_apps = self.load_apps()

        if not any(
            app.title.strip().lower() == original_title.strip().lower()
            and app.url.strip().lower() == original_url.strip().lower()
            for app in current_apps
        ):
            raise RegistryError("La app seleccionada ya no existe en el registro.")

        if app_exists_excluding(current_apps, updated_app.title, updated_app.url, original_title, original_url):
            raise DuplicateAppError("Ya existe otra app con el mismo nombre o con la misma URL.")

        updated = False
        for idx, item in enumerate(raw_apps):
            app = record_to_appcard(item)
            if app is None:
                continue
            if (
                app.title.strip().lower() == original_title.strip().lower()
                and app.url.strip().lower() == original_url.strip().lower()
            ):
                raw_apps[idx] = appcard_to_record(updated_app)
                updated = True
                break

        if not updated:
            raise RegistryError("No se encontró la app a editar en el registro.")

        self._write_payload(raw_apps)

    def delete_app(self, title: str, url: str) -> None:
        raw_data = self._read_raw()
        raw_apps = raw_data.get("apps", [])
        remaining_raw_apps: List[Dict[str, Any]] = []
        deleted = False

        for item in raw_apps:
            app = record_to_appcard(item)
            if app is None:
                continue
            if (
                app.title.strip().lower() == title.strip().lower()
                and app.url.strip().lower() == url.strip().lower()
            ):
                deleted = True
                continue
            remaining_raw_apps.append(item)

        if not deleted:
            raise RegistryError("No se encontró la app a eliminar en el registro.")

        self._write_payload(remaining_raw_apps)


# ======================================================
# BACKEND REMOTO GITHUB
# ======================================================


class GitHubJsonRegistryBackend:
    def __init__(self, token: str, owner: str, repo: str, branch: str, file_path: str) -> None:
        self.token = token
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.file_path = file_path.strip("/")
        self.info = RegistryBackendInfo(
            mode="github_contents_api",
            label="GitHub remoto",
            details=f"{self.owner}/{self.repo}@{self.branch}:{self.file_path}",
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "streamlit-central-hub-registry",
        }

    def _contents_url(self) -> str:
        encoded_path = parse.quote(self.file_path)
        return f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/contents/{encoded_path}"

    def _request_json(self, method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = None
        headers = self._headers()
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url, data=data, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            try:
                error_payload = json.loads(body_text) if body_text else {}
            except json.JSONDecodeError:
                error_payload = {"message": body_text}

            status_code = exc.code
            message = error_payload.get("message", f"GitHub API devolvió HTTP {status_code}.")

            if status_code == 404:
                raise FileNotFoundError(message) from exc
            if status_code in {409, 422}:
                raise RegistryConflictError(message) from exc
            if status_code in {401, 403}:
                raise RegistryError(
                    "No se pudo autenticar contra GitHub. Revisa token, permisos y repositorio configurado."
                ) from exc
            raise RegistryError(f"Error GitHub API ({status_code}): {message}") from exc
        except error.URLError as exc:
            raise RegistryError(f"No fue posible conectarse con GitHub: {exc.reason}") from exc

    def _load_records_and_sha(self) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        url = f"{self._contents_url()}?ref={parse.quote(self.branch)}"
        try:
            payload = self._request_json("GET", url)
        except FileNotFoundError:
            return [], None

        content = payload.get("content", "")
        encoding = payload.get("encoding", "")
        sha = payload.get("sha")

        if not content:
            return [], sha

        try:
            if encoding == "base64":
                decoded = base64.b64decode(content.encode("utf-8"))
                raw_text = decoded.decode("utf-8")
            else:
                raw_text = str(content)
            raw_data = json.loads(raw_text)
        except Exception as exc:
            raise RegistryError("El archivo remoto apps_registry.json está corrupto o no tiene JSON válido.") from exc

        if not isinstance(raw_data, dict):
            raw_data = {"apps": []}
        apps = raw_data.get("apps", [])
        if not isinstance(apps, list):
            apps = []

        return apps, sha

    def load_apps(self) -> List[AppCard]:
        raw_apps, _ = self._load_records_and_sha()
        valid_apps: List[AppCard] = []
        for item in raw_apps:
            app = record_to_appcard(item)
            if app is not None:
                valid_apps.append(app)
        return dedupe_apps(valid_apps)

    def _write_records(self, raw_apps: List[Dict[str, Any]], sha: Optional[str], message: str) -> None:
        payload_text = json.dumps({"apps": raw_apps}, ensure_ascii=False, indent=2)
        content_b64 = base64.b64encode(payload_text.encode("utf-8")).decode("utf-8")
        body: Dict[str, Any] = {
            "message": message,
            "content": content_b64,
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha
        self._request_json("PUT", self._contents_url(), body)

    def append_app(self, app: AppCard) -> None:
        last_error: Optional[Exception] = None
        for _ in range(3):
            try:
                raw_apps, sha = self._load_records_and_sha()
                current_apps = [x for x in (record_to_appcard(item) for item in raw_apps) if x is not None]
                current_apps = dedupe_apps(current_apps)

                if app_exists(current_apps, app.title, app.url):
                    raise DuplicateAppError("Ya existe una app con el mismo nombre o con la misma URL.")

                raw_apps.append(appcard_to_record(app))
                self._write_records(raw_apps, sha, message=f"Registrar app: {app.title}")
                return
            except RegistryConflictError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise RegistryError(
                "No se pudo guardar la app por un conflicto de escritura concurrente en GitHub. Intenta nuevamente."
            ) from last_error
        raise RegistryError("No se pudo guardar la app en el backend remoto.")

    def update_app(self, original_title: str, original_url: str, updated_app: AppCard) -> None:
        last_error: Optional[Exception] = None
        for _ in range(3):
            try:
                raw_apps, sha = self._load_records_and_sha()
                current_apps = [x for x in (record_to_appcard(item) for item in raw_apps) if x is not None]
                current_apps = dedupe_apps(current_apps)

                if not any(
                    app.title.strip().lower() == original_title.strip().lower()
                    and app.url.strip().lower() == original_url.strip().lower()
                    for app in current_apps
                ):
                    raise RegistryError("La app seleccionada ya no existe en el registro.")

                if app_exists_excluding(current_apps, updated_app.title, updated_app.url, original_title, original_url):
                    raise DuplicateAppError("Ya existe otra app con el mismo nombre o con la misma URL.")

                updated = False
                for idx, item in enumerate(raw_apps):
                    app = record_to_appcard(item)
                    if app is None:
                        continue
                    if (
                        app.title.strip().lower() == original_title.strip().lower()
                        and app.url.strip().lower() == original_url.strip().lower()
                    ):
                        raw_apps[idx] = appcard_to_record(updated_app)
                        updated = True
                        break

                if not updated:
                    raise RegistryError("No se encontró la app a editar en el registro.")

                self._write_records(raw_apps, sha, message=f"Editar app: {original_title} -> {updated_app.title}")
                return
            except RegistryConflictError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise RegistryError(
                "No se pudo actualizar la app por un conflicto de escritura concurrente en GitHub. Intenta nuevamente."
            ) from last_error
        raise RegistryError("No se pudo actualizar la app en el backend remoto.")

    def delete_app(self, title: str, url: str) -> None:
        last_error: Optional[Exception] = None
        for _ in range(3):
            try:
                raw_apps, sha = self._load_records_and_sha()
                remaining_raw_apps: List[Dict[str, Any]] = []
                deleted = False

                for item in raw_apps:
                    app = record_to_appcard(item)
                    if app is None:
                        continue
                    if (
                        app.title.strip().lower() == title.strip().lower()
                        and app.url.strip().lower() == url.strip().lower()
                    ):
                        deleted = True
                        continue
                    remaining_raw_apps.append(item)

                if not deleted:
                    raise RegistryError("No se encontró la app a eliminar en el registro.")

                self._write_records(remaining_raw_apps, sha, message=f"Eliminar app: {title}")
                return
            except RegistryConflictError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise RegistryError(
                "No se pudo eliminar la app por un conflicto de escritura concurrente en GitHub. Intenta nuevamente."
            ) from last_error
        raise RegistryError("No se pudo eliminar la app en el backend remoto.")


# ======================================================
# SELECCION DE BACKEND
# ======================================================


def _read_secret_section(section_name: str) -> Dict[str, Any]:
    try:
        section = st.secrets.get(section_name, {})
    except Exception:
        section = {}

    if hasattr(section, "to_dict"):
        return section.to_dict()
    if isinstance(section, dict):
        return dict(section)
    return {}



def get_registry_backend() -> Any:
    config = _read_secret_section("github_registry")

    token = normalize_text(str(config.get("token", "")))
    owner = normalize_text(str(config.get("owner", "")))
    repo = normalize_text(str(config.get("repo", "")))
    branch = normalize_text(str(config.get("branch", "main"))) or "main"
    file_path = normalize_text(str(config.get("path", DEFAULT_GITHUB_REGISTRY_PATH))) or DEFAULT_GITHUB_REGISTRY_PATH

    if token and owner and repo:
        return GitHubJsonRegistryBackend(
            token=token,
            owner=owner,
            repo=repo,
            branch=branch,
            file_path=file_path,
        )

    return LocalJsonRegistryBackend(REGISTRY_PATH)



def load_registry_apps(backend: Any) -> List[AppCard]:
    return backend.load_apps()



def get_all_apps(backend: Any) -> List[AppCard]:
    return dedupe_apps(DEFAULT_APPS + load_registry_apps(backend))



def get_all_areas(apps: List[AppCard]) -> List[Dict[str, str]]:
    area_icons = {item["name"]: item["icon"] for item in BASE_AREAS}
    ordered_names = [item["name"] for item in BASE_AREAS]

    for app in apps:
        if app.area not in area_icons:
            area_icons[app.area] = DEFAULT_CUSTOM_AREA_ICON
            ordered_names.append(app.area)

    return [{"name": name, "icon": area_icons[name]} for name in ordered_names]


# ======================================================
# ESTILOS
# ======================================================


def apply_global_styles() -> None:
    st.markdown(
        """
        <style>
        html {
            font-size: 11px;
        }

        :root {
            --hub-bg: #f5f7fb;
            --hub-surface: #ffffff;
            --hub-border: #d9dee8;
            --hub-border-soft: #e7ebf3;
            --hub-text: #16181d;
            --hub-muted: #5e6675;
            --hub-blue: #1684ea;
            --hub-blue-dark: #106fc9;
            --hub-red: #ff2b2b;
            --hub-red-dark: #ef2020;
            --hub-shadow: 0 8px 24px rgba(17, 24, 39, 0.05);
        }

        .stApp {
            background: var(--hub-bg);
        }

        [data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--hub-border-soft);
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stTextInput label,
        [data-testid="stSidebar"] .stRadio label {
            color: var(--hub-text);
        }

        .hub-sidebar-brand {
            padding: 0.25rem 0 1.2rem 0;
        }

        .hub-sidebar-title {
            font-size: 2rem;
            line-height: 1;
            font-weight: 800;
            letter-spacing: -0.03em;
            color: #111827;
            margin-bottom: 1rem;
        }

        .hub-sidebar-label {
            font-size: 0.9rem;
            font-weight: 700;
            color: #1f2937;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-top: 0.2rem;
            margin-bottom: 0.45rem;
        }

        .hub-page-header {
            display: flex;
            align-items: flex-start;
            justify-content: flex-start;
            gap: 1rem;
            margin-bottom: 1.1rem;
            flex-wrap: wrap;
        }

        .hub-page-title {
            font-size: clamp(1.75rem, 2.6vw, 2.55rem);
            font-weight: 800;
            color: var(--hub-text);
            line-height: 1.08;
            letter-spacing: -0.04em;
            margin: 0;
        }

        .hub-summary {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            background: #ffffff;
            border: 1px solid var(--hub-border-soft);
            border-radius: 16px;
            padding: 0.75rem 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.03);
            color: #334155;
            font-size: 0.98rem;
        }

        .hub-card-shell {
            padding: 0 0.6rem 1.35rem 0.6rem;
        }

        .hub-card {
            background: var(--hub-surface);
            border: 1px solid var(--hub-border);
            border-radius: 24px;
            box-shadow: var(--hub-shadow);
            padding: 1rem 1rem 0.95rem;
            display: flex;
            flex-direction: column;
            transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
        }

        .hub-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 14px 32px rgba(17, 24, 39, 0.09);
            border-color: #bfd4f7;
        }

        .hub-card-icon {
            width: 78px;
            height: 78px;
            margin: 0 auto 0.65rem auto;
            display: flex;
            align-items: center;
            justify-content: center;
            background: transparent;
            border: none;
            box-shadow: none;
        }

        .hub-card-icon-img {
            width: 78px;
            height: 78px;
            object-fit: contain;
            display: block;
        }

        .hub-card-title {
            text-align: center;
            font-size: 1.3rem;
            line-height: 1.18;
            font-weight: 800;
            color: #111827;
            margin: 0 0 0.4rem 0;
            letter-spacing: -0.03em;
        }

        .hub-card-desc {
            text-align: center;
            color: #374151;
            font-size: 0.96rem;
            line-height: 1.34;
            margin-bottom: 0.55rem;
        }

        .hub-card-button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: 42px;
            border-radius: 12px;
            text-decoration: none !important;
            background: linear-gradient(180deg, var(--hub-blue) 0%, var(--hub-blue-dark) 100%);
            color: #ffffff !important;
            font-weight: 800;
            font-size: 0.98rem;
            letter-spacing: 0.02em;
            box-shadow: 0 8px 18px rgba(22, 132, 234, 0.28);
            border: 1px solid rgba(255,255,255,0.25);
            transition: filter 0.18s ease, transform 0.18s ease;
        }

        .hub-card-button:hover {
            filter: brightness(1.03);
            transform: translateY(-1px);
        }

        .hub-card-button:visited,
        .hub-card-button:focus,
        .hub-card-button:active {
            color: #ffffff !important;
        }

        .st-key-open_add_app_form_slot,
        .st-key-open_add_app_form_empty_top {
            padding: 0 0.6rem 1.35rem 0.6rem !important;
            margin: 0 !important;
        }

        .st-key-open_add_app_form_slot .stButton,
        .st-key-open_add_app_form_empty_top .stButton {
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-open_add_app_form_slot > div,
        .st-key-open_add_app_form_empty_top > div {
            width: 100%;
        }

        .st-key-open_add_app_form_slot button,
        .st-key-open_add_app_form_empty_top button {
            width: 100%;
            min-height: 42px;
            border-radius: 12px;
            background: linear-gradient(180deg, var(--hub-red) 0%, var(--hub-red-dark) 100%) !important;
            color: #ffffff !important;
            font-weight: 800 !important;
            font-size: 0.98rem !important;
            letter-spacing: 0.02em;
            border: 1px solid rgba(255,255,255,0.2) !important;
            box-shadow: 0 8px 18px rgba(255, 43, 43, 0.28);
        }

        .st-key-open_add_app_form_slot button:hover,
        .st-key-open_add_app_form_empty_top button:hover {
            filter: brightness(1.03);
            transform: translateY(-1px);
            color: #ffffff !important;
        }

        .hub-empty-state {
            border: 1px dashed #cfd6e3;
            background: #ffffff;
            border-radius: 20px;
            padding: 2rem;
            text-align: center;
            color: #4b5563;
            margin-bottom: 1rem;
        }

        /* Sidebar: botones de áreas (sin rojo; seleccionado en azul transparente) */
        div[class*="st-key-area_"] button {
            width: 100% !important;
            border-radius: 10px !important;

            /* Variables (permiten que el seleccionado mantenga el mismo estilo incluso en hover/focus) */
            --area-bg: #ffffff;
            --area-border: #e5e7eb;
            --area-color: #111827;
            --area-bg-hover: rgba(22, 132, 234, 0.06);
            --area-border-hover: rgba(22, 132, 234, 0.26);

            background: var(--area-bg) !important;
            border: 1px solid var(--area-border) !important;
            color: var(--area-color) !important;
            font-weight: 700 !important;
            box-shadow: none !important;
        }

        div[class*="st-key-area_"] button:hover,
        div[class*="st-key-area_"] button:focus,
        div[class*="st-key-area_"] button:focus-visible {
            background: var(--area-bg-hover) !important;
            border-color: var(--area-border-hover) !important;
            color: var(--area-color) !important;
        }

        div[class*="st-key-area_"] button:active {
            transform: translateY(0px) !important;
        }

        .hub-important-label {
            margin-top: 1.05rem;
        }

        .hub-important-box {
            border-radius: 14px;
            border: 1px solid rgba(22, 132, 234, 0.22);
            border-left: 6px solid var(--hub-blue);
            background: rgba(22, 132, 234, 0.07);
            padding: 0.85rem 0.9rem;
            color: #0f172a;
            font-size: 0.95rem;
            line-height: 1.3;
        }
.hub-search-hint {
            color: #6b7280;
            font-size: 0.9rem;
            margin-top: -0.35rem;
            margin-bottom: 0.75rem;
        }

        .stTextInput > div > div input,
        .stTextArea textarea {
            border-radius: 14px;
            background: #ffffff;
            border: 1px solid #d9dee8;
        }

        @media (max-width: 900px) {
            .hub-card-shell {
                padding-left: 0;
                padding-right: 0;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ======================================================
# HELPERS UI
# ======================================================


DIALOG_DECORATOR = getattr(st, "dialog", getattr(st, "experimental_dialog", None))



def init_state() -> None:
    if "selected_area" not in st.session_state:
        st.session_state.selected_area = "Products Operations"
    if "flash_success" not in st.session_state:
        st.session_state.flash_success = ""
    if "flash_error" not in st.session_state:
        st.session_state.flash_error = ""



def set_area(area_name: str) -> None:
    st.session_state.selected_area = area_name



def sidebar_area_button(area_name: str, icon: str) -> None:
    """Botón de área en el sidebar (con estilo seleccionado en azul)."""
    slug = slugify_key(area_name)
    label = f"{icon}  {area_name}"

    st.button(
        label,
        key=f"area_{slug}",
        use_container_width=True,
        type="secondary",
        on_click=set_area,
        args=(area_name,),
    )




def render_sidebar(areas: List[Dict[str, str]], backend_info: RegistryBackendInfo) -> str:
    with st.sidebar:
        st.markdown('<div class="hub-sidebar-brand">', unsafe_allow_html=True)
        st.markdown('<div class="hub-sidebar-title">UTP - My Hub</div>', unsafe_allow_html=True)
        search_term = st.text_input(
            "Búsqueda global",
            placeholder="Global search...",
            label_visibility="collapsed",
        )
        st.markdown('<div class="hub-search-hint">Busca por nombre, descripción o URL.</div>', unsafe_allow_html=True)
        st.markdown('<div class="hub-sidebar-label">MIS ÁREAS</div>', unsafe_allow_html=True)
        with st.expander("Áreas", expanded=True):
            for area in areas:
                sidebar_area_button(area["name"], area["icon"])
        # st.caption(f"Persistencia activa: {backend_info.label}")
        # st.caption(backend_info.details)

        # ------------------------------
        # Importante (siempre visible)
        # ------------------------------
        st.markdown('<div class="hub-sidebar-label hub-important-label">Importante</div>', unsafe_allow_html=True)
        st.markdown(
            '\n'.join([
                '<div class="hub-important-box">',
                'Si al darle clic a "<strong>ACCEDER A APP</strong>" le aparece un recuadro de color azul con el siguiente texto "<strong>Yes, get this app back up!</strong>" darle clic para continuar.',
                '</div>',
            ]),
            unsafe_allow_html=True,
        )

        # Estilo del área seleccionada (relleno azul transparente)
        selected_slug = slugify_key(st.session_state.selected_area)
        st.markdown(
            f"""
            <style>
            .st-key-area_{selected_slug} button {{
                --area-bg: rgba(22, 132, 234, 0.16);
                --area-border: rgba(22, 132, 234, 0.38);
                --area-color: #0b3a6d;
                --area-bg-hover: rgba(22, 132, 234, 0.16);
                --area-border-hover: rgba(22, 132, 234, 0.38);
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("</div>", unsafe_allow_html=True)
    return search_term.strip().lower()



def filter_apps(apps: List[AppCard], selected_area: str, search_term: str) -> List[AppCard]:
    items = [app for app in apps if app.area == selected_area]
    if not search_term:
        return items

    filtered: List[AppCard] = []
    for app in items:
        haystack = " ".join([app.title, app.description, app.source_file, app.area, app.url]).lower()
        if search_term in haystack:
            filtered.append(app)
    return filtered



def render_header(selected_area: str, app_count: int, search_term: str) -> None:
    st.markdown(
        f"""
        <div class="hub-page-header">
            <div>
                <h1 class="hub-page-title">Área: {html.escape(selected_area)} | Módulo de Aplicaciones</h1>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    summary_text = (
        f"🔹 Área seleccionada: <strong>{html.escape(selected_area)}</strong> · "
        f"Apps visibles: <strong>{app_count}</strong>"
    )
    if search_term:
        summary_text += f" · Filtro: <strong>{html.escape(search_term)}</strong>"

    st.markdown(f'<div class="hub-summary">{summary_text}</div>', unsafe_allow_html=True)



def render_card(app: AppCard) -> None:
    title = html.escape(app.title)
    description = html.escape(app.description)
    url = html.escape(app.url, quote=True)
    icon_html = card_icon_markup(app)

    st.markdown(
        f"""
        <div class="hub-card-shell">
            <div class="hub-card">
                <div class="hub-card-icon">{icon_html}</div>
                <div class="hub-card-title">{title}</div>
                <div class="hub-card-desc">{description}</div>
                <a class="hub-card-button" href="{url}" target="_blank">ACCEDER A APP</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_add_new_button(button_key: str) -> bool:
    open_dialog = st.button(
        "AÑADIR NUEVA APP",
        key=button_key,
        use_container_width=True,
        type="primary",
    )
    return open_dialog

def render_apps_grid(apps: List[AppCard]) -> bool:
    open_dialog = False
    total_slots = len(apps) + 1

    for row_start in range(0, total_slots, 3):
        cols = st.columns(3, gap="large")
        for col_idx in range(3):
            slot_idx = row_start + col_idx
            if slot_idx >= total_slots:
                continue

            with cols[col_idx]:
                if slot_idx < len(apps):
                    render_card(apps[slot_idx])
                elif slot_idx == len(apps):
                    if render_add_new_button("open_add_app_form_slot"):
                        open_dialog = True

    return open_dialog

def render_empty_state() -> None:
    st.markdown(
        """
        <div class="hub-empty-state">
            <h3 style="margin-top:0; margin-bottom:0.5rem;">Sin resultados</h3>
            <div>No se encontraron aplicaciones con los filtros actuales.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_flash_messages() -> None:
    success_message = st.session_state.get("flash_success", "")
    error_message = st.session_state.get("flash_error", "")

    if success_message:
        st.success(success_message)
        st.session_state.flash_success = ""

    if error_message:
        st.error(error_message)

def build_app_from_form(
    title: str,
    area: str,
    description: str,
    url: str,
    icon: str,
) -> AppCard:
    clean_title = normalize_text(title)
    clean_area = normalize_text(area)
    clean_description = normalize_text(description)
    clean_url = normalize_text(url)
    clean_icon = normalize_text(icon) or DEFAULT_CUSTOM_ICON

    if not all([clean_title, clean_area, clean_description, clean_url]):
        raise RegistryError("Completa todos los campos obligatorios del formulario.")

    if not is_valid_url(clean_url):
        raise RegistryError("La URL ingresada no es válida. Debe iniciar con http:// o https://")

    return AppCard(
        title=clean_title,
        description=clean_description,
        source_file=DEFAULT_CUSTOM_SOURCE,
        url=clean_url,
        area=clean_area,
        icon=clean_icon,
    )

def persist_new_app(
    backend: Any,
    all_apps: List[AppCard],
    title: str,
    area: str,
    description: str,
    url: str,
    icon: str,
) -> None:
    new_app = build_app_from_form(title, area, description, url, icon)

    if app_exists(all_apps, new_app.title, new_app.url):
        raise DuplicateAppError("Ya existe una app con el mismo nombre o con la misma URL.")

    backend.append_app(new_app)
    st.session_state.selected_area = new_app.area
    st.session_state.flash_error = ""
    st.session_state.flash_success = f"La app '{new_app.title}' fue registrada correctamente en {backend.info.label}."

def persist_updated_app(
    backend: Any,
    all_apps: List[AppCard],
    original_app: AppCard,
    title: str,
    area: str,
    description: str,
    url: str,
    icon: str,
) -> None:
    updated_app = build_app_from_form(title, area, description, url, icon)

    if app_exists_excluding(all_apps, updated_app.title, updated_app.url, original_app.title, original_app.url):
        raise DuplicateAppError("Ya existe otra app con el mismo nombre o con la misma URL.")

    backend.update_app(original_app.title, original_app.url, updated_app)
    st.session_state.selected_area = updated_app.area
    st.session_state.flash_error = ""
    st.session_state.flash_success = f"La app '{updated_app.title}' fue actualizada correctamente en {backend.info.label}."



def persist_deleted_app(backend: Any, app_to_delete: AppCard) -> None:
    backend.delete_app(app_to_delete.title, app_to_delete.url)
    st.session_state.flash_error = ""
    st.session_state.flash_success = f"La app '{app_to_delete.title}' fue eliminada correctamente de {backend.info.label}."



def render_registry_edit_tab(backend: Any, all_apps: List[AppCard], registry_apps: List[AppCard]) -> None:
    if not registry_apps:
        st.info("No hay apps registradas para editar. Las apps fijas del código no se editan desde este modal.")
        return

    selected_index = st.selectbox(
        "Selecciona una app registrada",
        options=list(range(len(registry_apps))),
        format_func=lambda idx: format_registry_app_option(registry_apps[idx]),
        key="edit_registry_app_index",
    )
    selected_app = registry_apps[selected_index]

    with st.form("form_edit_app_modal", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            title = st.text_input("Nombre", value=selected_app.title)
            area = st.text_input("Área", value=selected_app.area)
            icon = st.text_input("Icono", value=selected_app.icon or DEFAULT_CUSTOM_ICON, help="Ej.: 🧩, 📚, 📈")
        with col2:
            url = st.text_input("URL", value=selected_app.url)
            description = st.text_area("Descripción", value=selected_app.description, height=120)

        action_col1, action_col2 = st.columns([1, 1])
        submit = action_col1.form_submit_button("Guardar cambios", use_container_width=True, type="primary")
        cancel = action_col2.form_submit_button("Cancelar", use_container_width=True)

        if cancel:
            st.rerun()

        if submit:
            try:
                persist_updated_app(backend, all_apps, selected_app, title, area, description, url, icon)
            except DuplicateAppError as exc:
                st.error(str(exc))
            except RegistryError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"Ocurrió un error inesperado al editar la app: {exc}")
            else:
                st.rerun()



def render_registry_delete_tab(backend: Any, registry_apps: List[AppCard]) -> None:
    if not registry_apps:
        st.info("No hay apps registradas para eliminar. Las apps fijas del código no se eliminan desde este modal.")
        return

    selected_index = st.selectbox(
        "Selecciona una app registrada",
        options=list(range(len(registry_apps))),
        format_func=lambda idx: format_registry_app_option(registry_apps[idx]),
        key="delete_registry_app_index",
    )
    selected_app = registry_apps[selected_index]

    st.warning("Esta acción eliminará la app del registro persistente. La acción es inmediata.")
    st.markdown(
        f"**Nombre:** {html.escape(selected_app.title)}\n\n"
        f"**Área:** {html.escape(selected_app.area)}\n\n"
        f"**URL:** {html.escape(selected_app.url)}"
    )

    with st.form("form_delete_app_modal", clear_on_submit=False):
        confirmation = st.text_input(
            "Escribe ELIMINAR para confirmar",
            placeholder="ELIMINAR",
        )
        action_col1, action_col2 = st.columns([1, 1])
        submit = action_col1.form_submit_button("Eliminar app", use_container_width=True, type="primary")
        cancel = action_col2.form_submit_button("Cancelar", use_container_width=True)

        if cancel:
            st.rerun()

        if submit:
            if normalize_text(confirmation).upper() != "ELIMINAR":
                st.error("Confirmación inválida. Debes escribir exactamente ELIMINAR.")
            else:
                try:
                    persist_deleted_app(backend, selected_app)
                except RegistryError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Ocurrió un error inesperado al eliminar la app: {exc}")
                else:
                    st.rerun()

if DIALOG_DECORATOR is not None:

    @DIALOG_DECORATOR("Gestionar apps", width="large")
    def show_add_app_dialog(backend: Any, all_apps: List[AppCard]) -> None:
        registry_apps = backend.load_apps()
        st.caption("Desde este modal puedes registrar, editar y eliminar apps persistidas. Las apps fijas del código permanecen protegidas.")

        tab_new, tab_edit, tab_delete = st.tabs(["Nueva app", "Editar app", "Eliminar app"])

        with tab_new:
            with st.form("form_add_app_modal", clear_on_submit=False):
                col1, col2 = st.columns(2)
                with col1:
                    title = st.text_input("Nombre", placeholder="Ej.: UTP Dashboard")
                    area = st.text_input("Área", value=st.session_state.selected_area)
                    icon = st.text_input("Icono", value=DEFAULT_CUSTOM_ICON, help="Ej.: 🧩, 📚, 📈")
                with col2:
                    url = st.text_input("URL", placeholder="https://...")
                    description = st.text_area("Descripción", height=120, placeholder="Describe brevemente la app")

                action_col1, action_col2 = st.columns([1, 1])
                submit = action_col1.form_submit_button("Guardar app", use_container_width=True, type="primary")
                cancel = action_col2.form_submit_button("Cancelar", use_container_width=True)

                if cancel:
                    st.rerun()

                if submit:
                    try:
                        persist_new_app(backend, all_apps, title, area, description, url, icon)
                    except DuplicateAppError as exc:
                        st.error(str(exc))
                    except RegistryError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"Ocurrió un error inesperado al registrar la app: {exc}")
                    else:
                        st.rerun()

        with tab_edit:
            render_registry_edit_tab(backend, all_apps, registry_apps)

        with tab_delete:
            render_registry_delete_tab(backend, registry_apps)

else:

    def show_add_app_dialog(backend: Any, all_apps: List[AppCard]) -> None:
        registry_apps = backend.load_apps()
        st.warning("Tu versión de Streamlit no soporta st.dialog. Actualiza Streamlit para usar el modal emergente.")
        tab_new, tab_edit, tab_delete = st.tabs(["Nueva app", "Editar app", "Eliminar app"])

        with tab_new:
            with st.form("form_add_app_fallback", clear_on_submit=False):
                col1, col2 = st.columns(2)
                with col1:
                    title = st.text_input("Nombre", placeholder="Ej.: UTP Dashboard")
                    area = st.text_input("Área", value=st.session_state.selected_area)
                    icon = st.text_input("Icono", value=DEFAULT_CUSTOM_ICON)
                with col2:
                    url = st.text_input("URL", placeholder="https://...")
                    description = st.text_area("Descripción", height=120, placeholder="Describe brevemente la app")

                submit = st.form_submit_button("Guardar app", type="primary")
                if submit:
                    try:
                        persist_new_app(backend, all_apps, title, area, description, url, icon)
                    except Exception as exc:
                        st.error(str(exc))
                    else:
                        st.rerun()

        with tab_edit:
            render_registry_edit_tab(backend, all_apps, registry_apps)

        with tab_delete:
            render_registry_delete_tab(backend, registry_apps)

# ======================================================
# MAIN
# ======================================================

def main() -> None:
    init_state()
    apply_global_styles()

    backend = get_registry_backend()
    all_apps = get_all_apps(backend)
    areas = get_all_areas(all_apps)

    available_area_names = [item["name"] for item in areas]
    if st.session_state.selected_area not in available_area_names:
        st.session_state.selected_area = available_area_names[0] if available_area_names else "Products Operations"

    search_term = render_sidebar(areas, backend.info)
    selected_area = st.session_state.selected_area
    visible_apps = filter_apps(all_apps, selected_area, search_term)

    render_header(selected_area, len(visible_apps), search_term)
    render_flash_messages()

    open_dialog = False

    if not visible_apps:
        render_empty_state()
        open_dialog = render_add_new_button("open_add_app_form_empty_top")
    else:
        open_dialog = render_apps_grid(visible_apps)

    if open_dialog:
        show_add_app_dialog(backend, all_apps)

if __name__ == "__main__":
    main()
