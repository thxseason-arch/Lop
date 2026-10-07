import datetime as dt
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .core import fetch_goes_data, generate_gif, process_and_render_scene

app = FastAPI(title='Muryllo plotts API', version='3.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])

SATELLITES = {'noaa-goes16': 'GOES-16 (East)', 'noaa-goes19': 'GOES-19 (East Operacional)'}
BANDS = [f'C{i:02d}' for i in range(1, 17)]

class SceneRequest(BaseModel):
    satellite: Literal['noaa-goes16', 'noaa-goes19'] = 'noaa-goes19'
    band: str = Field('C13', pattern=r'^C(0[1-9]|1[0-6])$')
    date: dt.date
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    min_lon: float = Field(..., ge=-180, le=180)
    max_lon: float = Field(..., ge=-180, le=180)
    min_lat: float = Field(..., ge=-90, le=90)
    max_lat: float = Field(..., ge=-90, le=90)
    interpolation: Literal['nearest', 'bilinear'] = 'nearest'
    glm: bool = False

class GifRequest(SceneRequest):
    duration_minutes: int = Field(180, ge=5, le=1440)
    interval_minutes: int = Field(30, ge=5, le=120)
    fps: int = Field(4, ge=1, le=20)


def validate_bbox(req):
    if req.min_lon >= req.max_lon or req.min_lat >= req.max_lat:
        raise HTTPException(400, 'A região selecionada é inválida.')


def get_fs():
    try:
        import s3fs
        return s3fs.S3FileSystem(anon=True)
    except Exception as exc:
        raise HTTPException(500, f'Falha ao carregar acesso S3/depêndencias: {type(exc).__name__}: {exc}') from exc

@app.get('/status')
def status():
    return {'status': 'OK', 'message': 'Backend Muryllo plotts carregado', 'version': app.version}

@app.get('/satellites')
def satellites():
    return [{'id': k, 'name': v} for k, v in SATELLITES.items()]

@app.get('/bands')
def bands():
    return [{'id': b, 'name': b} for b in BANDS]

@app.post('/generate')
def generate(req: SceneRequest):
    validate_bbox(req)
    try:
        fs = get_fs()
        s3_file = fetch_goes_data(fs, req.satellite, req.band, req.date, req.hour, req.minute)
        title = f"Muryllo plotts | {SATELLITES[req.satellite].split(' (')[0]} | {req.date.strftime('%d/%m/%Y')} {req.hour:02d}:{req.minute:02d} UTC"
        data = process_and_render_scene(fs, s3_file,
            {'min_lon': req.min_lon, 'max_lon': req.max_lon, 'min_lat': req.min_lat, 'max_lat': req.max_lat},
            req.date, req.hour, req.minute, req.satellite, show_glm=req.glm,
            interpolation=req.interpolation, band=req.band, info_title=title)
        return Response(content=data, media_type='image/png')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f'{type(exc).__name__}: {exc}') from exc

@app.post('/generate-gif')
def generate_gif_endpoint(req: GifRequest):
    validate_bbox(req)
    try:
        fs = get_fs()
        start_dt = dt.datetime.combine(req.date, dt.time(req.hour, req.minute))
        data = generate_gif(fs, req.satellite, req.band,
            {'min_lon': req.min_lon, 'max_lon': req.max_lon, 'min_lat': req.min_lat, 'max_lat': req.max_lat},
            start_dt, req.duration_minutes, req.interval_minutes, req.fps, req.glm, req.interpolation)
        return Response(content=data, media_type='image/gif')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f'{type(exc).__name__}: {exc}') from exc
